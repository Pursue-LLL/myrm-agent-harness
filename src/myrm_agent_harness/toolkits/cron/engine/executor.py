"""Single-job execution lifecycle.

Orchestrates the complete lifecycle of a single cron job execution:
run → record → deliver → update state → failure alert.

The ``JobExecutor`` holds references to store, delivery, and push callback
but owns no scheduling state — that remains in ``CronScheduler``.

[INPUT]
- toolkits.cron.types::CronConfig, (POS: Cron job domain types.)
- toolkits.cron.protocols::CronStore, (POS: Protocols for the cron toolkit.)
- toolkits.cron.delivery_guard::is_silent_output, (POS: Cron delivery guard.)
- infra.incremental.manager::IncrementalMonitorManager (POS: Incremental monitor lifecycle manager.)

[OUTPUT]
- JobExecutor: Manages the complete lifecycle of a single job execution.

[POS]
Single-job execution lifecycle.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import replace as dc_replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from nanoid import generate as nanoid

from myrm_agent_harness.infra.incremental.manager import IncrementalMonitorManager
from myrm_agent_harness.toolkits.cron.engine.helpers import (
    classify_transient_error,
    error_backoff_ms,
    resolve_failure_alert,
    should_send_failure_alert,
)
from myrm_agent_harness.toolkits.cron.engine.helpers import (
    extract_telemetry as _extract_telemetry,
)
from myrm_agent_harness.toolkits.cron.engine.integrity import (
    GENESIS_HASH,
    compute_integrity_hash,
)
from myrm_agent_harness.toolkits.cron.delivery_guard import is_silent_output
from myrm_agent_harness.toolkits.cron.engine.parser import compute_next_run
from myrm_agent_harness.toolkits.cron.types import (
    CronConfig,
    CronJob,
    CronRunRecord,
    DeliveryStatus,
    JobResult,
    JobStatus,
    RunStatus,
    ScheduleKind,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from myrm_agent_harness.toolkits.cron.protocols import (
        CronStore,
        JobRunner,
        PreFlightCondition,
        ResultDelivery,
    )

    PushCallback = Callable[[str, str, str, str], Coroutine[None, None, None]]

logger = logging.getLogger(__name__)

_SCHEDULE_ERROR_THRESHOLD = 3
_MAX_OUTPUT_CHARS = 8000
_MAX_CONTEXT_FROM_CHARS = 8000


def _output_hash(text: str) -> str:
    """SHA-256 hex digest (first 32 chars) of normalized output."""
    return hashlib.sha256(text.strip().encode()).hexdigest()[:32]


class JobExecutor:
    """Manages the complete lifecycle of a single job execution.

    Stateful only in the sense that it holds injected dependencies.
    All per-execution state is local to each ``run_and_record`` call.

    Integrates incremental monitoring: when enabled, computes delta between
    current output and baseline, skips delivery if no new content.
    """

    def __init__(
        self,
        store: CronStore,
        delivery: ResultDelivery,
        config: CronConfig | None = None,
        push_callback: PushCallback | None = None,
        pre_condition: PreFlightCondition | None = None,
    ) -> None:
        cfg = config or CronConfig()
        self._store = store
        self._delivery = delivery
        self._push_callback = push_callback
        self._pre_condition = pre_condition
        self._global_failure_delivery = cfg.failure_delivery
        self._global_failure_alert = cfg.failure_alert
        self._monitor_manager = IncrementalMonitorManager(store)

    async def run_and_record(
        self,
        job: CronJob,
        runner: JobRunner,
        *,
        context: str = "",
        trigger_source: str = "cron",
    ) -> None:
        """Execute a job, persist the run record, deliver results, update state."""
        self._current_trigger_source = trigger_source

        # 1. Pre-flight Condition check
        if self._pre_condition and job.pre_condition_script:
            should_run, injected_context = await self._pre_condition.evaluate(job)
            if not should_run:
                logger.info("Job %s skipped by pre-flight condition", job.id)
                await self._record_skipped_by_probe(job)
                return
            if injected_context:
                context = f"{injected_context}\n\n{context}" if context else injected_context

        context_from_text = await self._resolve_context_from(job)
        effective_context = (
            f"{context_from_text}\n\n{context}" if context_from_text and context else context_from_text or context
        )

        started = datetime.now(UTC)
        try:
            result = await asyncio.wait_for(
                runner.run(job, context=effective_context),
                timeout=job.timeout_seconds,
            )
        except TimeoutError:
            result = JobResult(
                success=False,
                error=f"Execution timed out after {job.timeout_seconds}s",
                exit_code=124,
            )
            logger.warning("Job %s timed out after %ds", job.id, job.timeout_seconds)

        if result.skipped:
            logger.info("Job %s skipped by runner: %s", job.id, result.skip_reason or "unknown")
            await self._record_skipped_by_runner(job, result.skip_reason)
            return

        finished = datetime.now(UTC)
        duration_ms = int((finished - started).total_seconds() * 1000)

        result = await self._apply_incremental_monitoring(job, result)

        model, usage_in, usage_out, usage_total = _extract_telemetry(result)
        delivery_status, delivery_error = await self._try_deliver(job, result)

        prev_hash = await self._store.get_latest_integrity_hash(job.id) or GENESIS_HASH

        run = CronRunRecord(
            id=nanoid(size=16),
            job_id=job.id,
            started_at=started,
            finished_at=finished,
            duration_ms=duration_ms,
            status=RunStatus.OK if result.success else RunStatus.ERROR,
            output=result.output[:_MAX_OUTPUT_CHARS] if result.output else None,
            error=result.error[:1000] if result.error else None,
            model=model,
            usage_input_tokens=usage_in,
            usage_output_tokens=usage_out,
            usage_total_tokens=usage_total,
            trigger_source=trigger_source,
            delivery_status=delivery_status,
            delivery_error=delivery_error,
            metadata=result.metadata,
            prev_hash=prev_hash,
        )
        integrity_hash = compute_integrity_hash(run, prev_hash)
        run = dc_replace(run, integrity_hash=integrity_hash)

        await self._store.save_run(run)
        await self._push_notification(job, result, delivery_status)

        new_failures = 0 if result.success else job.consecutive_failures + 1
        await self._update_after_run(job, result, new_failures, finished)

    # ------------------------------------------------------------------
    # Incremental Monitoring
    # ------------------------------------------------------------------

    async def _apply_incremental_monitoring(
        self,
        job: CronJob,
        result: JobResult,
    ) -> JobResult:
        """Apply incremental monitoring if enabled.

        Args:
            job: Job configuration.
            result: Raw execution result.

        Returns:
            Modified result with incremental_delta and adjusted exit_code.
        """
        if not job.monitor_config or not job.monitor_config.enabled:
            return result

        if not result.success:
            return result

        try:
            monitor, reset_reason = await self._monitor_manager.get_monitor(
                job.id,
                job.monitor_config,
            )

            is_baseline_run = monitor.is_baseline()
            delta = monitor.compute_delta(result.output)

            metadata = result.metadata or {}
            if reset_reason == "ttl_expired":
                metadata["baseline_reset"] = True
                metadata["reset_reason"] = reset_reason
                logger.info("Job %s: baseline expired and reset, establishing new baseline", job.id)
            elif is_baseline_run and reset_reason == "first_run":
                logger.info("Job %s: first run, establishing baseline", job.id)

            if not delta:
                logger.info(
                    "Job %s: no new content detected (baseline: %s)",
                    job.id,
                    is_baseline_run,
                )
                result = dc_replace(
                    result,
                    exit_code=0,
                    incremental_delta="",
                    metadata=metadata if metadata else None,
                )
            else:
                logger.info(
                    "Job %s: detected new content (%d bytes)",
                    job.id,
                    len(delta),
                )

                result = dc_replace(
                    result,
                    exit_code=1,
                    incremental_delta=delta,
                    metadata=metadata if metadata else None,
                )

            monitor.update_baseline(delta)
            await self._monitor_manager.save_monitor_state(
                job.id,
                monitor,
                job.monitor_config,
            )

        except Exception as exc:
            if job.monitor_config:
                failure_count = await self._monitor_manager.record_monitor_failure(
                    job.id,
                    job.monitor_config,
                    exc,
                )

                if failure_count >= 3:
                    logger.error(
                        "Monitor for job %s failed %d times consecutively (last failure: %s)",
                        job.id,
                        failure_count,
                        exc,
                    )
                else:
                    logger.warning(
                        "Incremental monitoring failed for job %s (%d/%d): %s (continuing with full output)",
                        job.id,
                        failure_count,
                        3,
                        exc,
                    )
            else:
                logger.warning(
                    "Incremental monitoring failed for job %s: %s (continuing with full output)",
                    job.id,
                    exc,
                )

        return result

    # ------------------------------------------------------------------
    # Delivery
    # ------------------------------------------------------------------

    async def _try_deliver(
        self,
        job: CronJob,
        result: JobResult,
    ) -> tuple[DeliveryStatus, str | None]:
        if job.delivery.channel == "none":
            return DeliveryStatus.SKIPPED, None

        if result.success:
            if result.exit_code == 0 and job.monitor_config and job.monitor_config.enabled:
                if result.metadata and result.metadata.get("baseline_reset"):
                    logger.info(
                        "Job %s: baseline reset detected, delivering notification despite exit_code=0",
                        job.id,
                    )
                else:
                    logger.info("Job %s: exit_code=0, no new content — skipping delivery", job.id)
                    return DeliveryStatus.SKIPPED, "no_new_content"

            output_text = (result.output or "").strip()
            if is_silent_output(output_text):
                logger.warning("Job %s: [SILENT] response — skipping delivery", job.id)
                return DeliveryStatus.SKIPPED, "silent_response"

            if job.deduplicate and output_text:
                current_hash = _output_hash(output_text)
                if current_hash == job.last_output_hash:
                    logger.warning("Job %s: duplicate output — skipping delivery", job.id)
                    return DeliveryStatus.SKIPPED, "duplicate_output"

        delivery_result = result
        if result.incremental_delta:
            delivery_result = dc_replace(result, output=result.incremental_delta)
            logger.info(
                "Job %s: delivering incremental delta (%d bytes, original: %d bytes)",
                job.id,
                len(result.incremental_delta),
                len(result.output),
            )

        try:
            await self._delivery.deliver(job, delivery_result)
        except Exception as exc:
            logger.warning("Delivery failed for job %s: %s", job.id, exc)
            return DeliveryStatus.FAILED, str(exc)[:500]

        if job.deduplicate and result.success:
            output_text = (result.output or "").strip()
            if output_text:
                job.last_output_hash = _output_hash(output_text)

        return DeliveryStatus.DELIVERED, None

    async def _push_notification(
        self,
        job: CronJob,
        result: JobResult,
        delivery_status: DeliveryStatus,
    ) -> None:
        if not self._push_callback:
            return
        if delivery_status == DeliveryStatus.SKIPPED:
            return

        level = "success" if result.success else "error"
        snippet = (result.output or "")[:100] if result.success else (result.error or "unknown")[:100]
        text = f"[{job.name}] {snippet}"
        try:
            await self._push_callback(job.user_id, job.name, text, level)
        except Exception as exc:
            logger.warning("Push notification failed for job %s: %s", job.id, exc)

    # ------------------------------------------------------------------
    # Context-from resolution
    # ------------------------------------------------------------------

    async def _resolve_context_from(self, job: CronJob) -> str:
        """Build injected context from referenced jobs' latest successful outputs."""
        if not job.context_from:
            return ""
        fragments: list[str] = []
        for ref_id in job.context_from:
            runs = await self._store.list_runs(ref_id, limit=1, status="ok")
            if not runs or not runs[0].output:
                continue
            ref_job = await self._store.get_job(ref_id)
            task_name = ref_job.name if ref_job else ref_id
            output = runs[0].output
            if len(output) > _MAX_CONTEXT_FROM_CHARS:
                output = output[:_MAX_CONTEXT_FROM_CHARS] + "\n[... output truncated ...]"
            fragments.append(f"## Output from task '{task_name}'\n\n{output}")
        return "\n\n---\n\n".join(fragments)

    # ------------------------------------------------------------------
    # State update after execution
    # ------------------------------------------------------------------

    async def _update_after_run(
        self,
        job: CronJob,
        result: JobResult,
        new_failures: int,
        finished: datetime,
    ) -> None:
        existing = await self._store.get_job(job.id)
        if existing is None:
            logger.info("Job %s was deleted during execution, skipping post-run update", job.id)
            return

        if job.schedule.kind == ScheduleKind.ONCE:
            await self._handle_once_completion(job, result, new_failures, finished)
            return

        if not result.success and new_failures > job.max_retries:
            job.status = JobStatus.PAUSED
            job.next_run_at = None
            logger.warning(
                "Job %s auto-paused: %d consecutive failures (max_retries=%d)",
                job.id,
                new_failures,
                job.max_retries,
            )
        elif result.success:
            try:
                job.next_run_at = compute_next_run(job.schedule, finished)
            except Exception as exc:
                self._handle_schedule_compute_error(job, exc, finished)
        else:
            backoff = error_backoff_ms(new_failures)
            job.next_run_at = finished + timedelta(milliseconds=backoff)

        job.last_run_at = finished
        job.last_status = RunStatus.OK if result.success else RunStatus.ERROR
        job.last_error = result.error if not result.success else None
        job.consecutive_failures = new_failures

        if result.success:
            job.last_failure_alert_at = None
        else:
            self._maybe_send_failure_alert(job, new_failures, finished)

        job.updated_at = datetime.now(UTC)
        await self._store.save_job(job)

    async def _handle_once_completion(
        self,
        job: CronJob,
        result: JobResult,
        new_failures: int,
        finished: datetime,
    ) -> None:
        if result.success and job.delete_after_run:
            await self._store.delete_job(job.id)
            return

        if result.success:
            job.status = JobStatus.COMPLETED
            job.consecutive_failures = 0
            job.last_failure_alert_at = None
        elif classify_transient_error(result.error or "") and new_failures <= job.max_retries:
            backoff = error_backoff_ms(new_failures)
            job.next_run_at = finished + timedelta(milliseconds=backoff)
            job.consecutive_failures = new_failures
            job.last_error = result.error
            logger.warning(
                "One-shot job %s: transient error, retrying in %dms (attempt %d/%d)",
                job.id,
                backoff,
                new_failures,
                job.max_retries,
            )
        else:
            job.status = JobStatus.PAUSED
            job.consecutive_failures = new_failures
            job.last_error = result.error
            self._maybe_send_failure_alert(job, new_failures, finished)

        if job.status != JobStatus.ACTIVE:
            job.next_run_at = None
        job.last_run_at = finished
        job.last_status = RunStatus.OK if result.success else RunStatus.ERROR
        job.updated_at = datetime.now(UTC)
        await self._store.save_job(job)

    def _handle_schedule_compute_error(self, job: CronJob, error: Exception, finished: datetime) -> None:
        """Handle schedule computation failure with fallback retry.

        Below threshold: sets a 60-second fallback next_run_at so the
        scheduler retries instead of leaving the job as a zombie.
        At threshold: auto-pauses the job.
        """
        job.consecutive_failures += 1
        if job.consecutive_failures >= _SCHEDULE_ERROR_THRESHOLD:
            job.status = JobStatus.PAUSED
            job.next_run_at = None
            logger.warning(
                "Job %s auto-paused: schedule expression keeps failing (%d times): %s",
                job.id,
                job.consecutive_failures,
                error,
            )
        else:
            job.next_run_at = finished + timedelta(seconds=60)
            logger.warning(
                "Job %s: schedule compute error (%s), will retry in 60s",
                job.id,
                error,
            )

    async def _record_skipped(self, job: CronJob, *, reason: str | None = None) -> None:
        """Record a SKIPPED run and advance job schedule.

        Used by both pre-flight probe skips and runner-level skips
        (e.g. heartbeat no-content).  Does not touch monitors.
        """
        now = datetime.now(UTC)
        run = CronRunRecord(
            id=nanoid(size=16),
            job_id=job.id,
            trigger_source=self._current_trigger_source,
            status=RunStatus.SKIPPED,
            started_at=now,
            finished_at=now,
            duration_ms=0,
            delivery_status=DeliveryStatus.SKIPPED,
            output=reason,
        )
        await self._store.save_run(run)

        job.status = JobStatus.ACTIVE
        if job.schedule.kind == ScheduleKind.CRON:
            try:
                job.next_run_at = compute_next_run(job.schedule, now)
            except Exception as e:
                self._handle_schedule_compute_error(job, e, now)
        elif job.schedule.kind == ScheduleKind.INTERVAL:
            job.next_run_at = now + timedelta(milliseconds=job.schedule.interval_ms)
        elif job.schedule.kind == ScheduleKind.ONCE:
            if job.delete_after_run:
                await self._store.delete_job(job.id)
                return
            job.status = JobStatus.COMPLETED
            job.next_run_at = None

        job.last_run_at = now
        job.last_status = RunStatus.SKIPPED
        job.updated_at = datetime.now(UTC)
        await self._store.save_job(job)

    async def _record_skipped_by_probe(self, job: CronJob) -> None:
        """Handle a job skipped by the pre-flight probe."""
        await self._record_skipped(job, reason="pre-flight-condition")

    async def _record_skipped_by_runner(self, job: CronJob, reason: str | None) -> None:
        """Handle a job skipped by the runner (e.g. heartbeat no-content)."""
        await self._record_skipped(job, reason=reason)

    # ------------------------------------------------------------------
    # Failure alerting (dual-layer: per-job + global)
    # ------------------------------------------------------------------

    def _maybe_send_failure_alert(self, job: CronJob, failures: int, now: datetime) -> None:
        alert_config = resolve_failure_alert(job, self._global_failure_alert)
        if not alert_config:
            return
        if not should_send_failure_alert(job, alert_config, now):
            return

        job.last_failure_alert_at = now

        error_snippet = (job.last_error or "unknown error")[:200]
        alert_result = JobResult(
            success=True,
            output=(
                f' Cron job "{job.name}" failed {failures} consecutive times.\n'
                f"Last error: {error_snippet}\n\n"
                f"The task has been auto-paused or will retry with backoff. "
                f"Please check the task configuration in Settings → Cron."
            ),
        )

        effective_delivery = alert_config.delivery or job.failure_delivery or self._global_failure_delivery
        alert_job = dc_replace(job, delivery=effective_delivery) if effective_delivery else job

        task = asyncio.create_task(self._delivery.deliver(alert_job, alert_result))
        task.add_done_callback(_log_alert_delivery_failure)
        logger.warning(
            "Failure alert sent for job %s (%d consecutive failures) via %s",
            job.id,
            failures,
            alert_job.delivery.channel,
        )


def _log_alert_delivery_failure(task: asyncio.Task[None]) -> None:
    """Callback for failure alert delivery tasks — log errors instead of silently swallowing."""
    exc = task.exception() if not task.cancelled() else None
    if exc:
        logger.warning("Failure alert delivery failed: %s", exc)
