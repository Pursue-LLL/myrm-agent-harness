"""Recording of runs that did not execute to completion: skipped and deferred.

[INPUT]
- toolkits.cron.engine.parser::compute_next_run (POS: next-run calculation)
- toolkits.cron.protocols::CronStore (POS: job and run persistence)
- toolkits.cron.types::CronJob, CronRunRecord, JobResult (POS: Cron job domain types.)

[OUTPUT]
- SkippedRunMixin: `_record_skipped` / `_record_deferred` and their probe / runner entry points

[POS]
Mixed into ``JobExecutor``. A skipped run advances the schedule without counting a
failure; a deferred run re-arms the job at the instant the runner says a repeat can
succeed. Neither touches incremental monitors or delivery.
"""

from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.cron.engine.parser import compute_next_run
from myrm_agent_harness.toolkits.cron.types import (
    CronJob,
    CronRunRecord,
    DeliveryStatus,
    JobResult,
    JobStatus,
    RunStatus,
    ScheduleKind,
)

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.cron.protocols import CronStore

logger = logging.getLogger(__name__)


class SkippedRunMixin:
    """Skipped / deferred run bookkeeping for ``JobExecutor``.

    Accesses JobExecutor members via self: _store, _current_trigger_source,
    _handle_schedule_compute_error.
    """

    _store: CronStore
    _current_trigger_source: str

    if TYPE_CHECKING:

        def _handle_schedule_compute_error(self, job: CronJob, error: Exception, finished: datetime) -> None: ...

    async def _record_skipped(self, job: CronJob, *, reason: str | None = None) -> None:
        """Record a SKIPPED run and advance job schedule.

        Used by both pre-flight probe skips and runner-level skips
        (e.g. heartbeat no-content).  Does not touch monitors.
        """
        now = datetime.now(UTC)
        await self._save_skipped_run(job, now, reason)

        job.status = JobStatus.ACTIVE
        if job.schedule.kind in (ScheduleKind.CRON, ScheduleKind.INTERVAL):
            try:
                job.next_run_at = compute_next_run(job.schedule, now)
            except Exception as e:
                self._handle_schedule_compute_error(job, e, now)
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

    async def _record_deferred(self, job: CronJob, result: JobResult) -> None:
        """Re-arm *job* at ``result.retry_at``: a SKIPPED run, no failure counted, schedule kept.

        Retrying before that instant only burns attempts, and failing would auto-pause the job.
        """
        now = datetime.now(UTC)
        await self._save_skipped_run(job, now, result.skip_reason or result.error)
        if await self._store.get_job(job.id) is None:
            logger.info("Job %s was deleted during execution, skipping deferral", job.id)
            return

        job.status = JobStatus.ACTIVE
        job.next_run_at = result.retry_at
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

    async def _save_skipped_run(self, job: CronJob, now: datetime, reason: str | None) -> None:
        await self._store.save_run(
            CronRunRecord(
                id=secrets.token_urlsafe(12),
                job_id=job.id,
                trigger_source=self._current_trigger_source,
                status=RunStatus.SKIPPED,
                started_at=now,
                finished_at=now,
                duration_ms=0,
                delivery_status=DeliveryStatus.SKIPPED,
                output=reason,
            )
        )
