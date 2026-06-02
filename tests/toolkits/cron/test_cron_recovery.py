"""Unit tests for StartupRecovery three-phase strategy."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

from myrm_agent_harness.toolkits.cron.engine.recovery import StartupRecovery
from myrm_agent_harness.toolkits.cron.types import (
    CronJob,
    DeliveryConfig,
    JobStatus,
    JobType,
    RunStatus,
    Schedule,
    ScheduleKind,
)

_NOW = datetime(2026, 3, 29, 12, 0, 0, tzinfo=UTC)
_SCHED_CRON = Schedule(kind=ScheduleKind.CRON, expr="0 * * * *")
_SCHED_ONCE = Schedule(kind=ScheduleKind.ONCE, run_at=_NOW + timedelta(hours=1))
_DELIVERY = DeliveryConfig(channel="none")


def _job(**overrides: object) -> CronJob:
    defaults: dict[str, object] = {
        "id": "j1",
        "user_id": "u1",
        "name": "test",
        "job_type": JobType.SHELL,
        "command": "echo hi",
        "schedule": _SCHED_CRON,
        "delivery": _DELIVERY,
        "status": JobStatus.ACTIVE,
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    defaults.update(overrides)
    return CronJob(**defaults)  # type: ignore[arg-type]


class TestRecoverStaleRuns:
    async def test_recovers_stale_job(self) -> None:
        stale_job = _job(
            next_run_at=None,
            last_run_at=_NOW - timedelta(hours=2),
            timeout_seconds=60,
        )
        store = AsyncMock()
        store.list_orphaned_active = AsyncMock(return_value=[stale_job])
        store.save_job = AsyncMock()

        execute_fn = AsyncMock()
        recovery = StartupRecovery(store=store, execute_fn=execute_fn)
        await recovery._recover_stale_runs()

        store.save_job.assert_called_once()
        saved_job = store.save_job.call_args[0][0]
        assert saved_job.last_status == RunStatus.ERROR
        assert saved_job.consecutive_failures == 1
        assert saved_job.next_run_at is not None

    async def test_skips_non_stale(self) -> None:
        """Job with next_run_at=None but last_run_at very recent is NOT stale."""
        fresh_job = _job(
            next_run_at=None,
            last_run_at=datetime.now(UTC) - timedelta(seconds=5),
            timeout_seconds=300,
        )
        store = AsyncMock()
        store.list_orphaned_active = AsyncMock(return_value=[fresh_job])
        store.save_job = AsyncMock()

        recovery = StartupRecovery(store=store, execute_fn=AsyncMock())
        await recovery._recover_stale_runs()

        store.save_job.assert_not_called()

    async def test_once_job_paused(self) -> None:
        stale_once = _job(
            schedule=_SCHED_ONCE,
            next_run_at=None,
            last_run_at=_NOW - timedelta(hours=2),
            timeout_seconds=60,
        )
        store = AsyncMock()
        store.list_orphaned_active = AsyncMock(return_value=[stale_once])
        store.save_job = AsyncMock()

        recovery = StartupRecovery(store=store, execute_fn=AsyncMock())
        await recovery._recover_stale_runs()

        saved = store.save_job.call_args[0][0]
        assert saved.status == JobStatus.PAUSED
        assert saved.next_run_at is None

    async def test_no_orphans(self) -> None:
        store = AsyncMock()
        store.list_orphaned_active = AsyncMock(return_value=[])
        store.save_job = AsyncMock()

        recovery = StartupRecovery(store=store, execute_fn=AsyncMock())
        await recovery._recover_stale_runs()

        store.save_job.assert_not_called()


class TestReplayMissedSlots:
    async def test_replays_missed(self) -> None:
        job = _job(
            last_run_at=_NOW - timedelta(hours=3),
        )
        store = AsyncMock()
        store.list_jobs = AsyncMock(return_value=[job])
        store.claim_due = AsyncMock()

        execute_fn = AsyncMock()
        recovery = StartupRecovery(store=store, execute_fn=execute_fn)
        await recovery._replay_missed_slots()

        store.claim_due.assert_called_once()

    async def test_skips_paused(self) -> None:
        job = _job(status=JobStatus.PAUSED, last_run_at=_NOW - timedelta(hours=3))
        store = AsyncMock()
        store.list_jobs = AsyncMock(return_value=[job])
        store.claim_due = AsyncMock()

        recovery = StartupRecovery(store=store, execute_fn=AsyncMock())
        await recovery._replay_missed_slots()

        store.claim_due.assert_not_called()

    async def test_skips_interval(self) -> None:
        job = _job(
            schedule=Schedule(kind=ScheduleKind.INTERVAL, interval_ms=60_000),
            last_run_at=_NOW - timedelta(hours=3),
        )
        store = AsyncMock()
        store.list_jobs = AsyncMock(return_value=[job])
        store.claim_due = AsyncMock()

        recovery = StartupRecovery(store=store, execute_fn=AsyncMock())
        await recovery._replay_missed_slots()

        store.claim_due.assert_not_called()

    async def test_skips_no_last_run(self) -> None:
        job = _job(last_run_at=None)
        store = AsyncMock()
        store.list_jobs = AsyncMock(return_value=[job])
        store.claim_due = AsyncMock()

        recovery = StartupRecovery(store=store, execute_fn=AsyncMock())
        await recovery._replay_missed_slots()

        store.claim_due.assert_not_called()

    async def test_no_jobs(self) -> None:
        store = AsyncMock()
        store.list_jobs = AsyncMock(return_value=[])
        store.claim_due = AsyncMock()

        recovery = StartupRecovery(store=store, execute_fn=AsyncMock())
        await recovery._replay_missed_slots()

        store.claim_due.assert_not_called()

    async def test_skips_error_backoff(self) -> None:
        """Job in error backoff should not be replayed."""
        now = datetime.now(UTC)
        job = _job(
            last_run_at=now - timedelta(seconds=10),
            last_status=RunStatus.ERROR,
            consecutive_failures=3,
            retry_backoff_ms=3_600_000,
        )
        store = AsyncMock()
        store.list_jobs = AsyncMock(return_value=[job])
        store.claim_due = AsyncMock()

        recovery = StartupRecovery(store=store, execute_fn=AsyncMock())
        await recovery._replay_missed_slots()

        store.claim_due.assert_not_called()


class TestExecuteDueWithinGrace:
    async def test_executes_due_jobs(self) -> None:
        due_job = _job(
            next_run_at=_NOW - timedelta(seconds=30),
            misfire_grace_seconds=300,
        )
        store = AsyncMock()
        store.list_jobs = AsyncMock(return_value=[due_job])
        store.claim_due = AsyncMock()

        execute_fn = AsyncMock()
        recovery = StartupRecovery(store=store, execute_fn=execute_fn)
        await recovery._execute_due_within_grace()

        store.claim_due.assert_called_once()

    async def test_skips_past_grace(self) -> None:
        past_grace = _job(
            next_run_at=_NOW - timedelta(hours=2),
            misfire_grace_seconds=60,
        )
        store = AsyncMock()
        store.list_jobs = AsyncMock(return_value=[past_grace])
        store.claim_due = AsyncMock()
        store.get_job = AsyncMock(return_value=past_grace)
        store.save_job = AsyncMock()

        recovery = StartupRecovery(store=store, execute_fn=AsyncMock())
        await recovery._execute_due_within_grace()

        store.claim_due.assert_called_once()

    async def test_no_due_jobs(self) -> None:
        store = AsyncMock()
        store.list_jobs = AsyncMock(return_value=[])
        store.claim_due = AsyncMock()

        recovery = StartupRecovery(store=store, execute_fn=AsyncMock())
        await recovery._execute_due_within_grace()

        store.claim_due.assert_not_called()


class TestRescheduleSkipped:
    async def test_reschedule_cron(self) -> None:
        job = _job(next_run_at=_NOW - timedelta(hours=1))
        store = AsyncMock()
        store.get_job = AsyncMock(return_value=job)
        store.save_job = AsyncMock()

        recovery = StartupRecovery(store=store, execute_fn=AsyncMock())
        await recovery.reschedule_skipped("j1")

        store.save_job.assert_called_once()
        saved = store.save_job.call_args[0][0]
        assert saved.next_run_at is not None
        assert saved.last_status == RunStatus.SKIPPED

    async def test_reschedule_once_completes(self) -> None:
        job = _job(schedule=_SCHED_ONCE)
        store = AsyncMock()
        store.get_job = AsyncMock(return_value=job)
        store.save_job = AsyncMock()

        recovery = StartupRecovery(store=store, execute_fn=AsyncMock())
        await recovery.reschedule_skipped("j1")

        saved = store.save_job.call_args[0][0]
        assert saved.status == JobStatus.COMPLETED
        assert saved.next_run_at is None

    async def test_reschedule_not_found(self) -> None:
        store = AsyncMock()
        store.get_job = AsyncMock(return_value=None)
        store.save_job = AsyncMock()

        recovery = StartupRecovery(store=store, execute_fn=AsyncMock())
        await recovery.reschedule_skipped("j1")

        store.save_job.assert_not_called()


class TestRunAllPhases:
    async def test_run_calls_all_phases(self) -> None:
        store = AsyncMock()
        store.list_orphaned_active = AsyncMock(return_value=[])
        store.list_jobs = AsyncMock(return_value=[])

        recovery = StartupRecovery(store=store, execute_fn=AsyncMock())
        await recovery.run()

        store.list_orphaned_active.assert_called_once()
        assert store.list_jobs.call_count == 2
