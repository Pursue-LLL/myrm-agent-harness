"""Three-phase startup recovery strategy.

Heals the scheduler state after an unclean shutdown:

- **Phase 1 — Stale-Run**: detect zombie tasks (claimed but never completed)
  and mark them as failed, then reschedule.
- **Phase 2 — Missed-Slot**: replay cron slots that fired during downtime.
- **Phase 3 — Grace Window**: execute due jobs still within misfire grace;
  skip and reschedule those past the grace period.

All recovery logic is encapsulated here; the scheduler only calls ``run()``.

[INPUT]
- toolkits.cron.types::CronJob, (POS: Cron job domain types.)
- toolkits.cron.protocols::CronStore (POS: Protocols for the cron toolkit.)

[OUTPUT]
- StartupRecovery: Encapsulates the three-phase startup recovery logic.

[POS]
Three-phase startup recovery strategy.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.cron.engine.helpers import (
    _ensure_utc,
)
from myrm_agent_harness.toolkits.cron.engine.helpers import (
    is_in_error_backoff as _is_in_error_backoff,
)
from myrm_agent_harness.toolkits.cron.engine.helpers import (
    is_past_misfire_grace as _is_past_grace,
)
from myrm_agent_harness.toolkits.cron.engine.helpers import (
    is_stale_run as _is_stale_run,
)
from myrm_agent_harness.toolkits.cron.engine.parser import compute_next_run, compute_prev_run
from myrm_agent_harness.toolkits.cron.types import (
    CronJob,
    JobStatus,
    RunStatus,
    ScheduleKind,
)

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.cron.protocols import CronStore

logger = logging.getLogger(__name__)

ExecuteFn = Callable[[CronJob], Coroutine[None, None, None]]


class StartupRecovery:
    """Encapsulates the three-phase startup recovery logic.

    Receives ``store`` for persistence and ``execute_fn`` as a callback
    to dispatch recovered jobs for execution (typically
    ``CronScheduler._execute_and_persist``).
    """

    def __init__(self, store: CronStore, execute_fn: ExecuteFn) -> None:
        self._store = store
        self._execute_fn = execute_fn
        self._bg_tasks: set[asyncio.Task[None]] = set()

    def _spawn(self, coro: Coroutine[None, None, None]) -> None:
        """Schedule a tracked fire-and-forget task, guarding against premature GC."""
        task = asyncio.create_task(coro)
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    async def run(self) -> None:
        """Execute all three recovery phases in order."""
        await self._recover_stale_runs()
        await self._replay_missed_slots()
        await self._execute_due_within_grace()

    # ------------------------------------------------------------------
    # Phase 1: Stale-Run recovery
    # ------------------------------------------------------------------

    async def _recover_stale_runs(self) -> None:
        """Heal zombie tasks (claimed but never completed due to crash)."""
        orphans = await self._store.list_orphaned_active()
        if not orphans:
            return

        now = datetime.now(UTC)
        recovered = 0
        for job in orphans:
            if not _is_stale_run(job, now):
                continue

            job.last_status = RunStatus.ERROR
            job.last_error = f"Stale run recovered on restart (timeout={job.timeout_seconds}s)"
            job.consecutive_failures += 1
            job.last_run_at = now

            if job.schedule.kind == ScheduleKind.ONCE:
                job.status = JobStatus.PAUSED
                job.next_run_at = None
            else:
                job.next_run_at = compute_next_run(job.schedule, now)

            job.updated_at = now
            await self._store.save_job(job)
            recovered += 1

        if recovered:
            logger.warning("Recovered %d stale runs on startup", recovered)

    # ------------------------------------------------------------------
    # Phase 2: Missed-Slot replay
    # ------------------------------------------------------------------

    async def _replay_missed_slots(self) -> None:
        """Re-execute cron slots missed during downtime."""
        all_active = await self._store.list_jobs()
        if not all_active:
            return

        now = datetime.now(UTC)
        replay: list[CronJob] = []

        for job in all_active:
            if job.status != JobStatus.ACTIVE:
                continue
            if job.schedule.kind != ScheduleKind.CRON:
                continue
            if job.last_run_at is None:
                continue
            if _is_in_error_backoff(job, now):
                continue

            prev_slot = compute_prev_run(job.schedule, now)
            if prev_slot and prev_slot > _ensure_utc(job.last_run_at):
                replay.append(job)

        if not replay:
            return

        logger.warning("Replaying %d missed cron slots after restart", len(replay))
        replay_ids = [j.id for j in replay]
        await self._store.claim_due(replay_ids)
        for job in replay:
            self._spawn(self._execute_fn(job))

    # ------------------------------------------------------------------
    # Phase 3: Grace-window execution
    # ------------------------------------------------------------------

    async def _execute_due_within_grace(self) -> None:
        """Execute jobs past due but still within misfire grace."""
        now = datetime.now(UTC)
        due = await self._store.list_jobs(due_before=now)
        if not due:
            return

        runnable: list[CronJob] = []
        skipped_ids: list[str] = []
        for job in due:
            if _is_past_grace(job, now):
                logger.warning("Startup skip: job %s past misfire grace", job.id)
                skipped_ids.append(job.id)
            elif _is_in_error_backoff(job, now):
                continue
            else:
                runnable.append(job)

        claim_ids = [j.id for j in runnable] + skipped_ids
        if claim_ids:
            await self._store.claim_due(claim_ids)

        for job_id in skipped_ids:
            await self.reschedule_skipped(job_id)

        if runnable:
            logger.warning("Cron scheduler: catching up %d due jobs", len(runnable))
            for job in runnable:
                self._spawn(self._execute_fn(job))

    async def reschedule_skipped(self, job_id: str) -> None:
        """Re-compute next_run for a job skipped due to misfire grace."""
        job = await self._store.get_job(job_id)
        if not job or job.status != JobStatus.ACTIVE:
            return
        now = datetime.now(UTC)
        if job.schedule.kind == ScheduleKind.ONCE:
            job.status = JobStatus.COMPLETED
            job.next_run_at = None
        else:
            job.next_run_at = compute_next_run(job.schedule, now)
        job.last_status = RunStatus.SKIPPED
        job.updated_at = now
        await self._store.save_job(job)
