"""Cron job validation and normalization helpers.

Split from ``manager.py`` so the CRUD orchestration file stays about persistence
ordering and scheduler notification, while the field-level rules that reject a job
live together and can be read (and tested) on their own.

[INPUT]
- cron.engine.parser::validate_cron_expr, validate_timezone (POS: cron 表达式与时区校验)
- cron.triggers::TriggerConfig, WebhookTrigger, generate_webhook_path, generate_webhook_secret (POS: webhook 触发定义与凭据生成)
- cron.types::CronJob, JobType, Schedule, ScheduleKind (POS: cron 数据模型)

[OUTPUT]
- CronValidationMixin: _validate_create / _validate_schedule / _validate_context_from /
  _validate_resume_preconditions / _ensure_webhook_credentials / _resolve_name_conflict

[POS]
Validation half of the cron CRUD manager. A mixin rather than free functions because every
rule either needs the job store (reference and name checks) or the shell-enabled policy, both
of which belong to the manager instance.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.cron.engine.parser import (
    validate_cron_expr,
    validate_timezone,
)
from myrm_agent_harness.toolkits.cron.triggers import (
    TriggerConfig,
    WebhookTrigger,
    generate_webhook_path,
    generate_webhook_secret,
)
from myrm_agent_harness.toolkits.cron.types import JobStatus, JobType, ScheduleKind

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.cron.protocols import CronStore
    from myrm_agent_harness.toolkits.cron.types import CronJob, Schedule


class CronValidationMixin:
    """Field-level validation for cron job creation, updates, and resumption."""

    if TYPE_CHECKING:
        # Provided by the concrete manager that composes this mixin.
        _store: CronStore
        _shell_enabled: bool

    @staticmethod
    def _validate_resume_preconditions(job: CronJob, now: datetime) -> None:
        """Reject resuming a job whose constraints make it immediately un-runnable."""
        if job.status == JobStatus.COMPLETED:
            raise ValueError("completed jobs cannot be resumed")
        if job.expires_at is not None:
            expires_at = job.expires_at if job.expires_at.tzinfo else job.expires_at.replace(tzinfo=UTC)
            if now >= expires_at:
                raise ValueError("job has expired; extend expires_at before resuming")
        if job.max_fires is not None and job.fire_count >= job.max_fires:
            raise ValueError("max execution count reached; increase max_fires before resuming")

    def _validate_create(
        self,
        job_type: JobType,
        schedule: Schedule,
        prompt: str | None,
        command: str | None,
    ) -> None:
        """Validate required fields by job type before persisting."""
        if job_type == JobType.SHELL:
            if not self._shell_enabled:
                raise ValueError("shell jobs are not enabled")
            if not command:
                raise ValueError("SHELL job requires a non-empty 'command'")
        elif not prompt:
            raise ValueError(f"{job_type.value.upper()} job requires a non-empty 'prompt'")

        self._validate_schedule(schedule)

    @staticmethod
    def _validate_schedule(schedule: Schedule) -> None:
        """Validate schedule cron expression and timezone."""
        if schedule.kind == ScheduleKind.CRON and not validate_cron_expr(schedule.expr):
            raise ValueError(f"invalid cron expression: {schedule.expr!r}")
        if schedule.tz and not validate_timezone(schedule.tz):
            raise ValueError(f"unknown timezone: {schedule.tz!r}")

    async def _validate_context_from(self, job_id: str, context_from: tuple[str, ...]) -> None:
        """Ensure context_from references are valid and non-circular."""
        for ref_id in context_from:
            if ref_id == job_id:
                raise ValueError(f"context_from must not reference the job itself: {ref_id!r}")
            ref_job = await self._store.get_job(ref_id)
            if ref_job is None:
                raise ValueError(f"context_from references non-existent job: {ref_id!r}")

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
