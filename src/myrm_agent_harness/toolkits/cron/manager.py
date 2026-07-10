"""Cron CRUD manager.

Orchestrates validation, persistence, and scheduler notification.
The ``CronManager`` is the single entry point for all job mutations
(used by both agent tools and API routes).


[INPUT]
- cron.engine.parser::compute_next_run, validate_cron_expr, validate_timezone (POS: cron expression parser and validator)
- cron.triggers::TriggerConfig, WebhookTrigger, generate_webhook_path, generate_webhook_secret (POS: event trigger definitions)
- cron.types::CronJob, CronJobPatch, JobStatus, JobType, ScheduleKind, etc. (POS: cron data models)
- cron.protocols::CronStore (POS: cron job persistence protocol)
- cron.engine.scheduler::CronScheduler (POS: timer-based scheduling engine)

[OUTPUT]
- CronManager: single entry point for all cron job CRUD operations with validation and scheduler sync

[POS]
Cron CRUD orchestration layer. Validates job configurations, persists changes via CronStore,
and notifies CronScheduler of mutations. Used by both agent tools and API routes.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from nanoid import generate as nanoid

from myrm_agent_harness.toolkits.cron.engine.parser import (
    compute_next_run,
    validate_cron_expr,
    validate_timezone,
)
from myrm_agent_harness.toolkits.cron.triggers import (
    TriggerConfig,
    WebhookTrigger,
    generate_webhook_path,
    generate_webhook_secret,
)
from myrm_agent_harness.toolkits.cron.types import (
    ActiveHours,
    CronJob,
    CronJobPatch,
    DeliveryConfig,
    FailureAlertConfig,
    JobStatus,
    JobType,
    ScheduleKind,
    SessionTarget,
)

if TYPE_CHECKING:
    from myrm_agent_harness.infra.incremental.types import MonitorConfig, MonitorState, ResetReason
    from myrm_agent_harness.toolkits.cron.engine.scheduler import CronScheduler
    from myrm_agent_harness.toolkits.cron.protocols import CronStore
    from myrm_agent_harness.toolkits.cron.types import CronRunRecord, Schedule

logger = logging.getLogger(__name__)


class CronManager:
    """CRUD orchestration for cron jobs.

    All mutations validate inputs, persist via ``CronStore``, and notify
    the ``CronScheduler`` so timer re-arms happen immediately.

    ``shell_enabled`` is set by the application layer (e.g. True in local mode,
    False in sandbox) to control whether shell jobs are allowed.
    """

    def __init__(
        self,
        store: CronStore,
        scheduler: CronScheduler,
        *,
        shell_enabled: bool = False,
    ) -> None:
        self._store = store
        self._scheduler = scheduler
        self._shell_enabled = shell_enabled

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    async def list_jobs(
        self,
        user_id: str,
        *,
        name_filter: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[CronJob]:
        return await self._store.list_jobs(user_id=user_id, name_filter=name_filter, limit=limit, offset=offset)

    async def count_jobs(self, user_id: str) -> int:
        return await self._store.count_jobs(user_id=user_id)

    async def get_job(self, job_id: str, user_id: str) -> CronJob | None:
        job = await self._store.get_job(job_id)
        if job and job.user_id != user_id:
            return None
        return job

    async def list_runs(
        self,
        user_id: str,
        *,
        job_id: str | None = None,
        limit: int = 20,
        offset: int = 0,
        status: str | None = None,
    ) -> list[CronRunRecord]:
        if job_id:
            job = await self._store.get_job(job_id)
            if not job or job.user_id != user_id:
                return []
        return await self._store.list_runs(job_id, limit=limit, offset=offset, status=status)

    async def count_runs(
        self,
        user_id: str,
        *,
        job_id: str | None = None,
        status: str | None = None,
    ) -> int:
        if job_id:
            job = await self._store.get_job(job_id)
            if not job or job.user_id != user_id:
                return 0
        return await self._store.count_runs(job_id, status=status)

    async def get_monitor_state(self, job_id: str) -> MonitorState | None:
        """Return the monitor state for a job, or None if not found."""
        return await self._store.get_monitor_state(job_id)

    async def batch_get_monitor_states(self, job_ids: list[str]) -> dict[str, MonitorState]:
        """Batch get monitor states for multiple jobs.

        Returns dict mapping job_id to MonitorState. Missing jobs are omitted.
        """
        return await self._store.batch_get_monitor_states(job_ids)

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    async def create_job(
        self,
        user_id: str,
        name: str,
        job_type: JobType,
        schedule: Schedule,
        *,
        prompt: str | None = None,
        model: str | None = None,
        chat_id: str | None = None,
        agent_id: str | None = None,
        command: str | None = None,
        delivery: DeliveryConfig | None = None,
        failure_delivery: DeliveryConfig | None = None,
        failure_alert: FailureAlertConfig | bool | None = None,
        active_hours: ActiveHours | None = None,
        required_capabilities: tuple[str, ...] = (),
        allowed_roots: tuple[str, ...] = (),
        max_retries: int = 2,
        retry_backoff_ms: int = 30_000,
        timeout_seconds: int = 300,
        misfire_grace_seconds: int = 300,
        cooldown_seconds: int = 0,
        max_fires: int | None = None,
        expires_at: datetime | None = None,
        session_target: SessionTarget = SessionTarget.ISOLATED,
        delete_after_run: bool | None = None,
        run_retention_days: int = 30,
        deduplicate: bool = False,
        monitor_config: MonitorConfig | None = None,
        triggers: TriggerConfig | None = None,
        context_from: tuple[str, ...] = (),
        pre_condition_script: str | None = None,
    ) -> CronJob:
        self._validate_create(job_type, schedule, prompt, command)

        if triggers:
            triggers = self._ensure_webhook_credentials(triggers)

        if delete_after_run is None:
            delete_after_run = schedule.kind == ScheduleKind.ONCE

        # Handle name conflicts: auto-append (2), (3), etc. if name exists
        final_name = await self._resolve_name_conflict(user_id, name)

        job_id = nanoid(size=16)
        if context_from:
            await self._validate_context_from(job_id, context_from)

        now = datetime.now(UTC)
        try:
            job = CronJob(
                id=job_id,
                user_id=user_id,
                name=final_name,
                job_type=job_type,
                schedule=schedule,
                status=JobStatus.ACTIVE,
                prompt=prompt,
                model=model,
                chat_id=chat_id,
                agent_id=agent_id,
                command=command,
                required_capabilities=required_capabilities,
                allowed_roots=allowed_roots,
                delivery=delivery or DeliveryConfig(),
                failure_delivery=failure_delivery,
                failure_alert=failure_alert,
                active_hours=active_hours,
                max_retries=max_retries,
                retry_backoff_ms=retry_backoff_ms,
                timeout_seconds=timeout_seconds,
                misfire_grace_seconds=misfire_grace_seconds,
                cooldown_seconds=cooldown_seconds,
                max_fires=max_fires,
                expires_at=expires_at,
                session_target=session_target,
                delete_after_run=delete_after_run,
                run_retention_days=run_retention_days,
                deduplicate=deduplicate,
                monitor_config=monitor_config,
                triggers=triggers,
                context_from=context_from,
                pre_condition_script=pre_condition_script,
                next_run_at=compute_next_run(schedule, now),
                created_at=now,
                updated_at=now,
            )
        except ValueError as e:
            # Config validation failed — reject entire job, no fallback
            logger.error("Cron job config validation failed: %s", e)
            raise ValueError(f"Config validation failed: {e}") from e

        job = await self._store.save_job(job)
        self._scheduler.notify_change()
        logger.warning("Cron job created: %s (%s)", name, job.id)
        return job

    async def duplicate_job(self, job_id: str, user_id: str) -> CronJob | None:
        """Duplicate an existing job with all configuration fields.

        Copies every config field from the source job while resetting all
        runtime state (fire_count, failures, run history, etc.).
        The new job starts in PAUSED status to prevent accidental triggering.
        Webhook triggers get fresh path/secret to avoid conflicts.
        """
        source = await self.get_job(job_id, user_id)
        if source is None:
            return None

        triggers = source.triggers
        if triggers and triggers.webhooks:
            triggers = self._ensure_webhook_credentials(
                TriggerConfig(
                    webhooks=tuple(WebhookTrigger() for _ in triggers.webhooks),
                    events=triggers.events,
                    system_events=triggers.system_events,
                    polls=triggers.polls,
                    streams=triggers.streams,
                ),
            )

        copy_name = f"{source.name} (Copy)"
        final_name = await self._resolve_name_conflict(user_id, copy_name)

        new_id = nanoid(size=16)
        now = datetime.now(UTC)
        cloned = CronJob(
            id=new_id,
            user_id=user_id,
            name=final_name,
            job_type=source.job_type,
            schedule=source.schedule,
            status=JobStatus.PAUSED,
            prompt=source.prompt,
            model=source.model,
            chat_id=source.chat_id,
            agent_id=source.agent_id,
            command=source.command,
            required_capabilities=source.required_capabilities,
            allowed_roots=source.allowed_roots,
            delivery=source.delivery,
            failure_delivery=source.failure_delivery,
            failure_alert=source.failure_alert,
            active_hours=source.active_hours,
            max_retries=source.max_retries,
            retry_backoff_ms=source.retry_backoff_ms,
            timeout_seconds=source.timeout_seconds,
            misfire_grace_seconds=source.misfire_grace_seconds,
            cooldown_seconds=source.cooldown_seconds,
            max_fires=source.max_fires,
            expires_at=source.expires_at,
            session_target=source.session_target,
            delete_after_run=source.delete_after_run,
            run_retention_days=source.run_retention_days,
            deduplicate=source.deduplicate,
            monitor_config=source.monitor_config,
            triggers=triggers,
            context_from=source.context_from,
            pre_condition_script=source.pre_condition_script,
            next_run_at=None,
            created_at=now,
            updated_at=now,
        )
        cloned = await self._store.save_job(cloned)
        self._scheduler.notify_change()
        logger.warning("Cron job duplicated: %s -> %s (%s)", source.name, final_name, new_id)
        return cloned

    async def _reset_baseline_on_change(self, job_id: str, reset_reason: ResetReason) -> None:
        """Reset monitor baseline and record reason.

        Called when command/prompt/monitor_type changes with enabled monitoring.
        Clears baseline data and persists reset metadata for user visibility.

        Args:
            job_id: Job identifier.
            reset_reason: Why the baseline was reset.
        """
        state = await self._store.get_monitor_state(job_id)
        if state:
            state.data = {}
            state.last_reset_at = datetime.now(UTC)
            state.last_reset_reason = reset_reason
            await self._store.save_monitor_state(state)
        else:
            await self._store.delete_monitor_state(job_id)
        logger.info(
            "Auto-reset monitor baseline due to %s change: %s",
            reset_reason.replace("_", "/"),
            job_id,
        )

    async def update_job(self, job_id: str, user_id: str, patch: CronJobPatch) -> CronJob | None:
        """Update job fields via patch.

        Auto-resets monitor baseline when command/prompt/monitor_type changes
        with enabled monitor.
        """
        job = await self._store.get_job(job_id)
        if not job or job.user_id != user_id:
            return None

        now = datetime.now(UTC)
        reset_reason: ResetReason | None = None

        if patch.name is not None:
            job.name = patch.name
        if patch.status is not None:
            job.status = patch.status
        if patch.schedule is not None:
            self._validate_schedule(patch.schedule)
            job.schedule = patch.schedule
            job.next_run_at = compute_next_run(patch.schedule, now)
        if patch.prompt is not None and patch.prompt != job.prompt:
            job.prompt = patch.prompt
            if job.monitor_config and job.monitor_config.enabled:
                reset_reason = "prompt_change"
        if patch.model is not None:
            job.model = patch.model
        if patch.agent_id is not None:
            job.agent_id = patch.agent_id
        if patch.command is not None and patch.command != job.command:
            job.command = patch.command
            if job.monitor_config and job.monitor_config.enabled:
                reset_reason = "command_change"
        if patch.delivery is not None:
            job.delivery = patch.delivery
        if patch.clear_failure_delivery:
            job.failure_delivery = None
        elif patch.failure_delivery is not None:
            job.failure_delivery = patch.failure_delivery
        if patch.clear_active_hours:
            job.active_hours = None
        elif patch.active_hours is not None:
            job.active_hours = patch.active_hours
        if patch.required_capabilities is not None:
            job.required_capabilities = patch.required_capabilities
        if patch.allowed_roots is not None:
            job.allowed_roots = patch.allowed_roots
        if patch.max_retries is not None:
            job.max_retries = patch.max_retries
        if patch.retry_backoff_ms is not None:
            job.retry_backoff_ms = patch.retry_backoff_ms
        if patch.timeout_seconds is not None:
            job.timeout_seconds = patch.timeout_seconds
        if patch.misfire_grace_seconds is not None:
            job.misfire_grace_seconds = patch.misfire_grace_seconds
        if patch.cooldown_seconds is not None:
            job.cooldown_seconds = patch.cooldown_seconds
        if patch.clear_max_fires:
            job.max_fires = None
        elif patch.max_fires is not None:
            job.max_fires = patch.max_fires
        if patch.clear_expires_at:
            job.expires_at = None
        elif patch.expires_at is not None:
            job.expires_at = patch.expires_at
        if patch.session_target is not None:
            job.session_target = patch.session_target
        if patch.clear_chat_id:
            job.chat_id = None
        elif patch.chat_id is not None:
            job.chat_id = patch.chat_id
        if patch.clear_failure_alert:
            job.failure_alert = False
        elif patch.failure_alert is not None:
            job.failure_alert = patch.failure_alert
        if patch.delete_after_run is not None:
            job.delete_after_run = patch.delete_after_run
        if patch.run_retention_days is not None:
            job.run_retention_days = patch.run_retention_days
        if patch.deduplicate is not None:
            job.deduplicate = patch.deduplicate
            if not patch.deduplicate:
                job.last_output_hash = None
        if patch.clear_monitor_config:
            job.monitor_config = None
        elif patch.monitor_config is not None:
            if (
                job.monitor_config
                and job.monitor_config.enabled
                and patch.monitor_config.monitor_type != job.monitor_config.monitor_type
            ):
                reset_reason = reset_reason or "monitor_type_change"
            job.monitor_config = patch.monitor_config
        if patch.clear_triggers:
            job.triggers = None
        elif patch.triggers is not None:
            job.triggers = self._ensure_webhook_credentials(patch.triggers)
        if patch.clear_context_from:
            job.context_from = ()
        elif patch.context_from is not None:
            await self._validate_context_from(job_id, patch.context_from)
            job.context_from = patch.context_from
        if patch.clear_pre_condition_script:
            job.pre_condition_script = None
        elif patch.pre_condition_script is not None:
            job.pre_condition_script = patch.pre_condition_script
        job.updated_at = now

        if reset_reason:
            try:
                await self._reset_baseline_on_change(job_id, reset_reason)
            except Exception:
                logger.warning(
                    "Failed to auto-reset monitor baseline for job %s, baseline may be stale until next run",
                    job_id,
                    exc_info=True,
                )

        job = await self._store.save_job(job)
        self._scheduler.notify_change()
        return job

    async def delete_job(self, job_id: str, user_id: str) -> bool:
        job = await self._store.get_job(job_id)
        if not job or job.user_id != user_id:
            return False
        deleted = await self._store.delete_job_cascade(job_id)
        if deleted:
            self._scheduler.notify_change()
        return deleted

    async def reset_monitor_baseline(self, job_id: str, user_id: str) -> bool:
        """Reset monitor baseline to restart incremental tracking.

        Args:
            job_id: Job identifier.
            user_id: User identifier (for permission check).

        Returns:
            True if baseline was reset, False if job not found or no baseline exists.

        Use cases:
            - Recover from corrupted baseline data
            - Restart monitoring after changing job scope
            - Testing and debugging
        """
        job = await self._store.get_job(job_id)
        if not job or job.user_id != user_id:
            return False

        state = await self._store.get_monitor_state(job_id)
        if not state:
            return False

        state.data = {}
        state.last_reset_at = datetime.now(UTC)
        state.last_reset_reason = "manual"
        await self._store.save_monitor_state(state)
        logger.info("Manually reset monitor baseline for job %s (user: %s)", job_id, user_id)

        return True

    async def pause_job(self, job_id: str, user_id: str) -> CronJob | None:
        return await self.update_job(job_id, user_id, CronJobPatch(status=JobStatus.PAUSED))

    async def resume_job(self, job_id: str, user_id: str) -> CronJob | None:
        job = await self._store.get_job(job_id)
        if not job or job.user_id != user_id:
            return None

        now = datetime.now(UTC)
        job.status = JobStatus.ACTIVE
        job.next_run_at = compute_next_run(job.schedule, now)
        job.consecutive_failures = 0
        job.updated_at = now

        job = await self._store.save_job(job)
        self._scheduler.notify_change()
        return job

    async def trigger_now(self, job_id: str, user_id: str) -> bool:
        """Set next_run_at to now so the scheduler picks it up immediately."""
        job = await self._store.get_job(job_id)
        if not job or job.user_id != user_id or job.status != JobStatus.ACTIVE:
            return False

        job.next_run_at = datetime.now(UTC)
        await self._store.save_job(job)
        self._scheduler.notify_change()
        return True

    # ------------------------------------------------------------------
    # Validation & Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_create(
        job_type: JobType,
        schedule: Schedule,
        prompt: str | None,
        command: str | None,
    ) -> None:
        """Validate required fields by job type before persisting."""
        if job_type == JobType.SHELL:
            if not command:
                raise ValueError("SHELL job requires a non-empty 'command'")
        elif not prompt:
            raise ValueError(f"{job_type.value.upper()} job requires a non-empty 'prompt'")

    @staticmethod
    def _ensure_webhook_credentials(triggers: TriggerConfig) -> TriggerConfig:
        """Fill in missing path/secret for each webhook trigger."""
        if not triggers.webhooks:
            return triggers
        patched = tuple(
            WebhookTrigger(
                path=wh.path or generate_webhook_path(),
                secret=wh.secret or generate_webhook_secret(),
            )
            for wh in triggers.webhooks
        )
        return TriggerConfig(
            webhooks=patched,
            events=triggers.events,
            system_events=triggers.system_events,
            polls=triggers.polls,
            streams=triggers.streams,
        )

    async def _resolve_name_conflict(self, user_id: str, name: str) -> str:
        """Auto-append (2), (3), etc. if name already exists for this user.

        Args:
            user_id: User identifier for scope isolation
            name: Desired task name

        Returns:
            Unique name (original or with suffix like " (2)")
        """
        # Query store directly to avoid mock issues in tests
        existing_jobs = await self._store.list_jobs(user_id=user_id)
        existing_names = {job.name for job in existing_jobs}

        if name not in existing_names:
            return name

        # Find next available suffix: (2), (3), ...
        suffix = 2
        while f"{name} ({suffix})" in existing_names:
            suffix += 1

        return f"{name} ({suffix})"
