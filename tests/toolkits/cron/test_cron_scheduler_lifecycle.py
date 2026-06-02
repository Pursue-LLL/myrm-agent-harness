"""Unit tests for CronScheduler lifecycle, timer machinery, and execution paths.

Covers start/stop, _arm_timer_async fallback, _arm_watchdog, _on_tick,
_execute_and_persist guard branches, and purge logic.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.toolkits.cron.engine.scheduler import CronScheduler
from myrm_agent_harness.toolkits.cron.types import (
    CronConfig,
    CronJob,
    DeliveryConfig,
    JobResult,
    JobStatus,
    JobType,
    Schedule,
    ScheduleKind,
)


def _make_job(**overrides: object) -> CronJob:
    defaults: dict[str, object] = {
        "id": "job-1",
        "user_id": "user-1",
        "name": "Test Job",
        "job_type": JobType.AGENT,
        "schedule": Schedule(kind=ScheduleKind.CRON, expr="0 * * * *"),
        "status": JobStatus.ACTIVE,
        "prompt": "test prompt",
        "delivery": DeliveryConfig(channel="chat"),
    }
    defaults.update(overrides)
    return CronJob(**defaults)  # type: ignore[arg-type]


def _make_store() -> AsyncMock:
    store = AsyncMock()
    store.list_jobs = AsyncMock(return_value=[])
    store.earliest_next_run = AsyncMock(return_value=None)
    store.save_run = AsyncMock()
    store.save_job = AsyncMock(side_effect=lambda j: j)
    store.get_latest_integrity_hash = AsyncMock(return_value=None)
    store.claim_due = AsyncMock()
    store.purge_old_runs = AsyncMock(return_value=0)
    store.delete_job = AsyncMock()
    return store


def _make_scheduler(
    store: AsyncMock | None = None,
    lock: AsyncMock | None = None,
    pre_condition: AsyncMock | None = None,
) -> tuple[CronScheduler, AsyncMock, AsyncMock]:
    store = store or _make_store()
    runner = AsyncMock()
    runner.run = AsyncMock(return_value=JobResult(success=True, output="ok"))
    delivery = AsyncMock()

    sched = CronScheduler(
        store=store,
        runners={JobType.AGENT: runner},
        delivery=delivery,
        config=CronConfig(),
        lock=lock,
        pre_condition=pre_condition,
    )
    return sched, store, runner


class TestStartStop:
    @pytest.mark.asyncio
    async def test_start_sets_running(self) -> None:
        sched, _store, _ = _make_scheduler()
        await sched.start()
        assert sched.health()["running"] is True
        await sched.stop()

    @pytest.mark.asyncio
    async def test_start_idempotent(self) -> None:
        sched, _, _ = _make_scheduler()
        await sched.start()
        await sched.start()
        assert sched.health()["running"] is True
        await sched.stop()

    @pytest.mark.asyncio
    async def test_stop_clears_running(self) -> None:
        sched, _, _ = _make_scheduler()
        await sched.start()
        await sched.stop()
        assert sched.health()["running"] is False

    @pytest.mark.asyncio
    async def test_start_with_lock_acquired(self) -> None:
        lock = AsyncMock()
        lock.try_acquire = AsyncMock(return_value=True)
        lock.release = AsyncMock()

        sched, _, _ = _make_scheduler(lock=lock)
        await sched.start()
        assert sched.health()["running"] is True
        lock.try_acquire.assert_awaited_once()
        await sched.stop()
        lock.release.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_start_with_lock_not_acquired(self) -> None:
        lock = AsyncMock()
        lock.try_acquire = AsyncMock(return_value=False)

        sched, _, _ = _make_scheduler(lock=lock)
        await sched.start()
        assert sched.health()["running"] is False
        await asyncio.sleep(0.05)


class TestHealth:
    @pytest.mark.asyncio
    async def test_health_initial_state(self) -> None:
        sched, _, _ = _make_scheduler()
        h = sched.health()
        assert h["running"] is False
        assert h["tick_errors"] == 0
        assert h["last_tick_at"] is None
        assert h["last_purge_at"] is None


class TestArmTimerAsync:
    @pytest.mark.asyncio
    async def test_arm_timer_no_next_wake(self) -> None:
        store = _make_store()
        store.earliest_next_run = AsyncMock(return_value=None)
        sched, _, _ = _make_scheduler(store=store)
        sched._running = True
        await sched._arm_timer_async()
        assert sched._timer_handle is None

    @pytest.mark.asyncio
    async def test_arm_timer_with_future_next_wake(self) -> None:
        store = _make_store()
        future_time = datetime.now(UTC) + timedelta(seconds=10)
        store.earliest_next_run = AsyncMock(return_value=future_time)
        sched, _, _ = _make_scheduler(store=store)
        sched._running = True
        await sched._arm_timer_async()
        assert sched._timer_handle is not None
        sched._timer_handle.cancel()

    @pytest.mark.asyncio
    async def test_arm_timer_with_past_next_wake(self) -> None:
        store = _make_store()
        past_time = datetime.now(UTC) - timedelta(seconds=10)
        store.earliest_next_run = AsyncMock(return_value=past_time)
        sched, _, _ = _make_scheduler(store=store)
        sched._running = True
        await sched._arm_timer_async()
        assert sched._timer_handle is not None
        sched._timer_handle.cancel()

    @pytest.mark.asyncio
    async def test_arm_timer_db_failure_retries(self) -> None:
        store = _make_store()
        store.earliest_next_run = AsyncMock(side_effect=RuntimeError("DB down"))
        sched, _, _ = _make_scheduler(store=store)
        sched._running = True
        await sched._arm_timer_async()
        assert sched._timer_handle is not None
        sched._timer_handle.cancel()


class TestArmWatchdog:
    @pytest.mark.asyncio
    async def test_arm_watchdog_when_running(self) -> None:
        sched, _, _ = _make_scheduler()
        sched._running = True
        sched._arm_watchdog()
        assert sched._watchdog_handle is not None
        sched._watchdog_handle.cancel()

    @pytest.mark.asyncio
    async def test_arm_watchdog_when_stopped(self) -> None:
        sched, _, _ = _make_scheduler()
        sched._running = False
        sched._arm_watchdog()
        assert sched._watchdog_handle is None

    @pytest.mark.asyncio
    async def test_arm_watchdog_replaces_existing(self) -> None:
        sched, _, _ = _make_scheduler()
        sched._running = True
        sched._arm_watchdog()
        old_handle = sched._watchdog_handle
        sched._arm_watchdog()
        assert sched._watchdog_handle is not old_handle
        if sched._watchdog_handle:
            sched._watchdog_handle.cancel()


class TestOnTick:
    @pytest.mark.asyncio
    async def test_on_tick_not_running(self) -> None:
        sched, store, _ = _make_scheduler()
        sched._running = False
        await sched._on_tick()
        store.list_jobs.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_on_tick_already_in_progress(self) -> None:
        sched, store, _ = _make_scheduler()
        sched._running = True
        sched._tick_in_progress = True
        await sched._on_tick()
        store.list_jobs.assert_not_awaited()
        if sched._watchdog_handle:
            sched._watchdog_handle.cancel()

    @pytest.mark.asyncio
    async def test_on_tick_no_due_jobs(self) -> None:
        store = _make_store()
        store.list_jobs = AsyncMock(return_value=[])
        sched, _, _ = _make_scheduler(store=store)
        sched._running = True
        await sched._on_tick()
        assert sched._last_tick_at is not None
        assert sched._tick_errors == 0
        if sched._watchdog_handle:
            sched._watchdog_handle.cancel()
        if sched._timer_handle:
            sched._timer_handle.cancel()

    @pytest.mark.asyncio
    async def test_on_tick_with_due_jobs(self) -> None:
        job = _make_job()
        store = _make_store()
        store.list_jobs = AsyncMock(return_value=[job])
        sched, _, _ = _make_scheduler(store=store)
        sched._running = True

        with patch.object(sched, "_execute_and_persist", new_callable=AsyncMock):
            await sched._on_tick()

        store.claim_due.assert_awaited_once()
        assert sched._tick_errors == 0
        if sched._watchdog_handle:
            sched._watchdog_handle.cancel()
        if sched._timer_handle:
            sched._timer_handle.cancel()

    @pytest.mark.asyncio
    async def test_on_tick_exception_increments_errors(self) -> None:
        store = _make_store()
        store.list_jobs = AsyncMock(side_effect=RuntimeError("store fail"))
        sched, _, _ = _make_scheduler(store=store)
        sched._running = True
        await sched._on_tick()
        assert sched._tick_errors == 1
        if sched._watchdog_handle:
            sched._watchdog_handle.cancel()
        if sched._timer_handle:
            sched._timer_handle.cancel()


class TestExecuteAndPersist:
    @pytest.mark.asyncio
    async def test_expired_job_skipped(self) -> None:
        store = _make_store()
        sched, _, _ = _make_scheduler(store=store)
        sched._running = True

        with patch(
            "myrm_agent_harness.toolkits.cron.engine.scheduler.pre_execution_check",
            return_value="expired",
        ):
            await sched._execute_and_persist(_make_job())

        store.save_job.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_max_fires_reached_skipped(self) -> None:
        store = _make_store()
        sched, _, _ = _make_scheduler(store=store)
        sched._running = True

        with patch(
            "myrm_agent_harness.toolkits.cron.engine.scheduler.pre_execution_check",
            return_value="max_fires_reached",
        ):
            await sched._execute_and_persist(_make_job())

        store.save_job.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_other_skip_reason_no_save(self) -> None:
        store = _make_store()
        sched, _, _ = _make_scheduler(store=store)
        sched._running = True

        with patch(
            "myrm_agent_harness.toolkits.cron.engine.scheduler.pre_execution_check",
            return_value="paused",
        ):
            await sched._execute_and_persist(_make_job())

        store.save_job.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_outside_active_hours_skipped(self) -> None:
        store = _make_store()
        sched, _, _ = _make_scheduler(store=store)
        sched._running = True

        with (
            patch(
                "myrm_agent_harness.toolkits.cron.engine.scheduler.pre_execution_check",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.toolkits.cron.engine.scheduler.is_within_active_hours",
                return_value=False,
            ),
        ):
            await sched._execute_and_persist(_make_job())

        store.save_run.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_skip_if_active_blocks(self) -> None:
        store = _make_store()
        sched, _, _ = _make_scheduler(store=store)
        sched._running = True
        sched._active_jobs.add("job-1")

        job = _make_job(skip_if_active=True)
        with (
            patch(
                "myrm_agent_harness.toolkits.cron.engine.scheduler.pre_execution_check",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.toolkits.cron.engine.scheduler.is_within_active_hours",
                return_value=True,
            ),
            patch(
                "myrm_agent_harness.toolkits.cron.engine.scheduler._resolve_stagger_ms",
                return_value=0,
            ),
        ):
            await sched._execute_and_persist(job)

        store.save_run.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_runner_for_job_type(self) -> None:
        store = _make_store()
        runner = AsyncMock()
        runner.run = AsyncMock(return_value=JobResult(success=True, output="ok"))
        delivery = AsyncMock()

        sched = CronScheduler(
            store=store,
            runners={JobType.AGENT: runner},
            delivery=delivery,
            config=CronConfig(),
        )
        sched._running = True

        job = _make_job(job_type=JobType.SHELL)
        with (
            patch(
                "myrm_agent_harness.toolkits.cron.engine.scheduler.pre_execution_check",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.toolkits.cron.engine.scheduler.is_within_active_hours",
                return_value=True,
            ),
            patch(
                "myrm_agent_harness.toolkits.cron.engine.scheduler._resolve_stagger_ms",
                return_value=0,
            ),
        ):
            await sched._execute_and_persist(job)

        store.save_run.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_stagger_delay_applied(self) -> None:
        store = _make_store()
        sched, _, _runner = _make_scheduler(store=store)
        sched._running = True

        schedule = Schedule(kind=ScheduleKind.CRON, expr="0 * * * *", stagger_ms=100)
        job = _make_job(schedule=schedule)
        with (
            patch(
                "myrm_agent_harness.toolkits.cron.engine.scheduler.pre_execution_check",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.toolkits.cron.engine.scheduler.is_within_active_hours",
                return_value=True,
            ),
            patch(
                "myrm_agent_harness.toolkits.cron.engine.scheduler._resolve_stagger_ms",
                return_value=100,
            ),
            patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        ):
            await sched._execute_and_persist(job)

        mock_sleep.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_execution_exception_handled(self) -> None:
        store = _make_store()
        sched, _, _ = _make_scheduler(store=store)
        sched._running = True

        with (
            patch(
                "myrm_agent_harness.toolkits.cron.engine.scheduler.pre_execution_check",
                side_effect=RuntimeError("unexpected"),
            ),
        ):
            await sched._execute_and_persist(_make_job())


class TestPurge:
    @pytest.mark.asyncio
    async def test_purge_runs_on_first_tick(self) -> None:
        store = _make_store()
        store.purge_old_runs = AsyncMock(return_value=5)
        sched, _, _ = _make_scheduler(store=store)
        sched._running = True
        await sched._maybe_purge_old_runs(datetime.now(UTC))
        store.purge_old_runs.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_purge_skipped_within_interval(self) -> None:
        store = _make_store()
        sched, _, _ = _make_scheduler(store=store)
        sched._last_purge_at = datetime.now(UTC)
        await sched._maybe_purge_old_runs(datetime.now(UTC))
        store.purge_old_runs.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_purge_exception_handled(self) -> None:
        store = _make_store()
        store.purge_old_runs = AsyncMock(side_effect=RuntimeError("disk error"))
        sched, _, _ = _make_scheduler(store=store)
        sched._running = True
        await sched._maybe_purge_old_runs(datetime.now(UTC))
