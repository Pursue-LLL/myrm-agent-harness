"""Cron scheduling engine.

Precise timer-based scheduler: computes exact sleep duration to the next due
job instead of fixed-interval polling.  Due jobs are dispatched into async
tasks bounded by a concurrency semaphore.

Execution lifecycle is delegated to ``JobExecutor``; startup recovery to
``StartupRecovery``.  This module owns only the timer machinery and
concurrency control.


[INPUT]
- cron.engine.executor::JobExecutor (POS: job execution lifecycle manager)
- cron.engine.helpers::_ensure_utc, is_within_active_hours, pre_execution_check, etc. (POS: scheduling helper utilities)
- cron.engine.recovery::StartupRecovery (POS: startup recovery for missed jobs)
- cron.types::CronConfig, CronJob, JobType (POS: cron data models)

[OUTPUT]
- CronScheduler: precise timer-based scheduling engine with concurrency control and watchdog

[POS]
Cron scheduling engine. Computes exact sleep durations to the next due job, dispatches
due jobs into async tasks with semaphore-based concurrency control, and delegates execution
to JobExecutor.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.cron.engine.executor import JobExecutor
from myrm_agent_harness.toolkits.cron.engine.helpers import (
    _ensure_utc,
    is_within_active_hours,
    pre_execution_check,
)
from myrm_agent_harness.toolkits.cron.engine.helpers import (
    is_past_misfire_grace as _is_past_grace,
)
from myrm_agent_harness.toolkits.cron.engine.helpers import (
    resolve_stagger_ms as _resolve_stagger_ms,
)
from myrm_agent_harness.toolkits.cron.engine.recovery import StartupRecovery
from myrm_agent_harness.toolkits.cron.types import (
    CronConfig,
    CronJob,
    JobType,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from myrm_agent_harness.toolkits.cron.protocols import (
        ConcurrencyLock,
        CronStore,
        JobRunner,
        PreFlightCondition,
        ResultDelivery,
        TriggerProvider,
    )

    PushCallback = Callable[[str, str, str, str], Coroutine[None, None, None]]

logger = logging.getLogger(__name__)

_FALLBACK_RETRY_SECONDS = 30
_PURGE_INTERVAL_SECONDS = 86_400
_DEFAULT_RETENTION_DAYS = 30
_MIN_REFIRE_GAP_S = 2.0
_WATCHDOG_INTERVAL_S = 60.0


class CronScheduler:
    """Precise timer-based cron scheduler.

    Instantiated once by the application layer, started in the server
    lifespan.  The ``notify_change`` callback is used by ``CronManager``
    after any job mutation to re-arm the timer.
    """

    def __init__(
        self,
        store: CronStore,
        runners: dict[JobType, JobRunner],
        delivery: ResultDelivery,
        config: CronConfig | None = None,
        lock: ConcurrencyLock | None = None,
        push_callback: PushCallback | None = None,
        trigger_provider: TriggerProvider | None = None,
        pre_condition: PreFlightCondition | None = None,
    ) -> None:
        cfg = config or CronConfig()
        self._store = store
        self._runners = runners
        self._lock = lock
        self._trigger_provider = trigger_provider

        self._running = False
        self._tick_in_progress = False
        self._timer_handle: asyncio.TimerHandle | None = None
        self._watchdog_handle: asyncio.TimerHandle | None = None
        self._last_tick_at: datetime | None = None
        self._tick_errors: int = 0
        self._global_sem = asyncio.Semaphore(cfg.max_concurrent)
        self._user_sems: dict[str, asyncio.Semaphore] = {}
        self._max_per_user = cfg.max_per_user

        self._last_purge_at: datetime | None = None
        self._active_jobs: set[str] = set()
        self._bg_tasks: set[asyncio.Task[None]] = set()
        self._push_callback = push_callback

        self._executor = JobExecutor(
            store=store,
            delivery=delivery,
            config=cfg,
            push_callback=push_callback,
            pre_condition=pre_condition,
        )
        self._recovery = StartupRecovery(
            store=store,
            execute_fn=self._execute_and_persist,
        )

    def _spawn(self, coro: Coroutine[object, object, None]) -> None:
        """Schedule a tracked fire-and-forget task, guarding against premature GC."""
        task = asyncio.create_task(coro)
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def notify_change(self) -> None:
        """Re-arm the timer after a job mutation (called by CronManager)."""
        self._arm_timer()

    def health(self) -> dict[str, str | int | bool | None]:
        return {
            "running": self._running,
            "last_tick_at": self._last_tick_at.isoformat() if self._last_tick_at else None,
            "tick_errors": self._tick_errors,
            "has_timer": self._timer_handle is not None,
            "last_purge_at": self._last_purge_at.isoformat() if self._last_purge_at else None,
        }

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if self._running:
            return

        if self._lock:
            acquired = await self._lock.try_acquire("cron:scheduler:lock", ttl_seconds=60)
            if not acquired:
                logger.warning("Cron scheduler: another worker holds the lock, standing by")
                loop = asyncio.get_running_loop()
                loop.call_later(30, lambda: asyncio.ensure_future(self.start()))
                return

        self._running = True
        await self._recovery.run()
        self._arm_timer()
        logger.info("Cron scheduler started")

    async def stop(self) -> None:
        self._running = False
        if self._timer_handle:
            self._timer_handle.cancel()
            self._timer_handle = None
        if self._watchdog_handle:
            self._watchdog_handle.cancel()
            self._watchdog_handle = None
        if self._lock:
            await self._lock.release("cron:scheduler:lock")
        logger.info("Cron scheduler stopped")

    # ------------------------------------------------------------------
    # Timer machinery
    # ------------------------------------------------------------------

    def _arm_timer(self) -> None:
        if not self._running:
            return
        if self._timer_handle:
            self._timer_handle.cancel()
        with contextlib.suppress(RuntimeError):
            self._spawn(self._arm_timer_async())

    async def _arm_timer_async(self) -> None:
        try:
            next_wake = await self._store.earliest_next_run()
        except Exception as exc:
            logger.warning("Failed to query next run: %s — retrying in %ds", exc, _FALLBACK_RETRY_SECONDS)
            loop = asyncio.get_running_loop()
            self._timer_handle = loop.call_later(
                _FALLBACK_RETRY_SECONDS,
                lambda: loop.create_task(self._on_tick()),
            )
            return

        if next_wake is None:
            return

        delay = max(0.0, (_ensure_utc(next_wake) - datetime.now(UTC)).total_seconds())
        if delay == 0:
            delay = _MIN_REFIRE_GAP_S
        delay = min(delay, _WATCHDOG_INTERVAL_S)
        loop = asyncio.get_running_loop()
        self._timer_handle = loop.call_later(delay, lambda: loop.create_task(self._on_tick()))

    def _arm_watchdog(self) -> None:
        """Keep a safety timer alive so the scheduler recovers from hangs."""
        if self._watchdog_handle:
            self._watchdog_handle.cancel()
        if not self._running:
            return
        try:
            loop = asyncio.get_running_loop()
            self._watchdog_handle = loop.call_later(
                _WATCHDOG_INTERVAL_S,
                lambda: loop.create_task(self._on_tick()),
            )
        except RuntimeError:
            pass

    async def _on_tick(self) -> None:
        if not self._running:
            return
        if self._tick_in_progress:
            self._arm_watchdog()
            return
        self._tick_in_progress = True
        self._arm_watchdog()
        try:
            now = datetime.now(UTC)
            due_jobs = await self._store.list_jobs(due_before=now)

            runnable: list[CronJob] = []
            skipped_ids: list[str] = []
            for job in due_jobs:
                if _is_past_grace(job, now):
                    logger.warning("Job %s skipped: past misfire grace", job.id)
                    skipped_ids.append(job.id)
                else:
                    runnable.append(job)

            claim_ids = [j.id for j in runnable] + skipped_ids
            if claim_ids:
                await self._store.claim_due(claim_ids)

            for job_id in skipped_ids:
                await self._recovery.reschedule_skipped(job_id)

            for job in runnable:
                self._spawn(self._execute_and_persist(job))

            self._last_tick_at = now
            self._tick_errors = 0

            await self._maybe_purge_old_runs(now)
        except Exception as exc:
            self._tick_errors += 1
            logger.warning("Cron tick failed (errors=%d): %s", self._tick_errors, exc)
        finally:
            self._tick_in_progress = False
            self._arm_timer()

    # ------------------------------------------------------------------
    # Run record housekeeping
    # ------------------------------------------------------------------

    async def _maybe_purge_old_runs(self, now: datetime) -> None:
        if self._last_purge_at and (now - self._last_purge_at).total_seconds() < _PURGE_INTERVAL_SECONDS:
            return
        try:
            cutoff = now - timedelta(days=_DEFAULT_RETENTION_DAYS)
            deleted = await self._store.purge_old_runs(before=cutoff)
            self._last_purge_at = now
            if deleted > 0:
                logger.warning("Purged %d old cron run records (before %s)", deleted, cutoff.isoformat())
        except Exception as exc:
            logger.warning("Failed to purge old runs: %s", exc)

    # ------------------------------------------------------------------
    # Trigger dispatch (event-driven execution)
    # ------------------------------------------------------------------

    async def dispatch_event(
        self,
        message: str,
        channel: str,
        user_id: str,
    ) -> int:
        """Check event triggers against an incoming message.

        Returns the number of jobs triggered.  When no ``TriggerProvider``
        is injected, returns 0 immediately.
        """
        if not self._trigger_provider:
            return 0
        try:
            jobs = await self._trigger_provider.check_event_triggers(message, channel, user_id)
        except Exception as exc:
            logger.warning("Event trigger check failed: %s", exc)
            return 0

        context = f"[TRIGGER: event]\nChannel: {channel}\nUser: {user_id}\nMessage: {message}"
        for job in jobs:
            self._spawn(self._execute_and_persist(job, context=context, trigger_source="event"))
        return len(jobs)

    async def dispatch_system_event(
        self,
        source: str,
        event_type: str,
        payload: dict[str, object],
    ) -> int:
        """Check system-event triggers.  Returns the number of jobs triggered."""
        if not self._trigger_provider:
            return 0
        try:
            jobs = await self._trigger_provider.check_system_event(source, event_type, payload)
        except Exception as exc:
            logger.warning("System event trigger check failed: %s", exc)
            return 0

        import json

        payload_str = json.dumps(payload, ensure_ascii=False, default=str)[:4000]
        context = f"[TRIGGER: system_event]\nSource: {source}\nEvent: {event_type}\nPayload:\n{payload_str}"
        for job in jobs:
            self._spawn(self._execute_and_persist(job, context=context, trigger_source="system_event"))
        return len(jobs)

    async def dispatch_webhook(
        self,
        path: str,
        secret: str,
        payload: dict[str, object],
    ) -> CronJob | None:
        """Validate and execute a webhook-triggered job.

        Returns the matched ``CronJob`` or ``None``.
        """
        if not self._trigger_provider:
            return None
        try:
            job = await self._trigger_provider.handle_webhook(path, secret, payload)
        except Exception as exc:
            logger.warning("Webhook trigger failed for path %s: %s", path, exc)
            return None

        if job is None:
            return None

        import json

        payload_str = json.dumps(payload, ensure_ascii=False, default=str)[:4000]
        context = f"[TRIGGER: webhook]\nPath: {path}\nPayload:\n{payload_str}"
        self._spawn(self._execute_and_persist(job, context=context, trigger_source="webhook"))
        return job

    # ------------------------------------------------------------------
    # Execution dispatch (stagger + concurrency + delegate to executor)
    # ------------------------------------------------------------------

    def _user_sem(self, user_id: str) -> asyncio.Semaphore:
        sem = self._user_sems.get(user_id)
        if sem is None:
            sem = asyncio.Semaphore(self._max_per_user)
            self._user_sems[user_id] = sem
        return sem

    async def _execute_and_persist(
        self,
        job: CronJob,
        *,
        context: str = "",
        trigger_source: str = "cron",
    ) -> None:
        try:
            now = datetime.now(UTC)
            skip_reason = pre_execution_check(job, now)
            if skip_reason:
                logger.warning("Job %s skipped: %s", job.id, skip_reason)
                if skip_reason in ("expired", "max_fires_reached"):
                    await self._store.save_job(job)
                    if self._push_callback:
                        reason_text = (
                            f"[{job.name}] 已到期，自动暂停"
                            if skip_reason == "expired"
                            else f"[{job.name}] 已达最大执行次数({job.max_fires})，自动暂停"
                        )
                        try:
                            await self._push_callback(job.user_id, job.name, reason_text, "warning")
                        except Exception as exc:
                            logger.warning("Push notification failed for paused job %s: %s", job.id, exc)
                return

            if not is_within_active_hours(job.active_hours):
                logger.warning("Job %s skipped: outside active hours", job.id)
                return

            if job.skip_if_active and job.id in self._active_jobs:
                logger.warning("Job %s skipped: previous instance still running (skip_if_active)", job.id)
                return

            stagger = _resolve_stagger_ms(job)
            if stagger > 0:
                delay_ms = random.randint(0, stagger)
                logger.warning("Job %s: stagger delay %dms", job.id, delay_ms)
                await asyncio.sleep(delay_ms / 1000)

            runner = self._runners.get(job.job_type)
            if not runner:
                logger.warning("No runner registered for job type %s", job.job_type)
                return

            self._active_jobs.add(job.id)
            try:
                async with self._global_sem, self._user_sem(job.user_id):
                    job.fire_count += 1
                    await self._executor.run_and_record(
                        job,
                        runner,
                        context=context,
                        trigger_source=trigger_source,
                    )
            finally:
                self._active_jobs.discard(job.id)
        except Exception as exc:
            logger.warning("Unhandled error in job %s: %s", job.id, exc)
