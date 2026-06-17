"""Integration tests for real cron job scenarios.

Uses InMemoryCronStore as a real store (no mocks) to validate
the full lifecycle: create → schedule → execute → deliver → state update.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from myrm_agent_harness.toolkits.cron.engine.executor import JobExecutor
from myrm_agent_harness.toolkits.cron.engine.scheduler import CronScheduler
from myrm_agent_harness.toolkits.cron.manager import CronManager
from myrm_agent_harness.toolkits.cron.stores import InMemoryCronStore
from myrm_agent_harness.toolkits.cron.types import (
    CronConfig,
    CronJob,
    DeliveryConfig,
    JobResult,
    JobStatus,
    JobType,
    RunStatus,
    Schedule,
    ScheduleKind,
)


class FakeAgentRunner:
    """Simulates an agent runner that returns a fixed response."""

    def __init__(self, output: str = "Agent completed task", success: bool = True) -> None:
        self._output = output
        self._success = success
        self.call_count = 0

    async def run(self, job: CronJob, *, context: str = "") -> JobResult:
        self.call_count += 1
        return JobResult(
            success=self._success,
            output=self._output,
            error=None if self._success else "Agent failed",
        )


class FakeShellRunner:
    """Simulates a shell runner."""

    def __init__(self, output: str = "shell output", exit_code: int = 0) -> None:
        self._output = output
        self._exit_code = exit_code
        self.call_count = 0

    async def run(self, job: CronJob, *, context: str = "") -> JobResult:
        self.call_count += 1
        return JobResult(
            success=self._exit_code == 0,
            output=self._output,
            exit_code=self._exit_code,
            error=f"exit code {self._exit_code}" if self._exit_code != 0 else None,
        )


class FakeDelivery:
    """Captures delivered results for assertion."""

    def __init__(self) -> None:
        self.deliveries: list[tuple[CronJob, JobResult]] = []

    async def deliver(self, job: CronJob, result: JobResult) -> None:
        self.deliveries.append((job, result))


# ---------------------------------------------------------------------------
# Scenario 1: Full lifecycle — create, execute, verify state
# ---------------------------------------------------------------------------


class TestFullLifecycle:
    """Create a job via CronManager, execute it via JobExecutor, verify state."""

    @pytest.fixture
    def store(self) -> InMemoryCronStore:
        return InMemoryCronStore()

    @pytest.fixture
    def delivery(self) -> FakeDelivery:
        return FakeDelivery()

    @pytest.fixture
    def agent_runner(self) -> FakeAgentRunner:
        return FakeAgentRunner()

    @pytest.fixture
    def executor(self, store: InMemoryCronStore, delivery: FakeDelivery) -> JobExecutor:
        return JobExecutor(store=store, delivery=delivery)

    @pytest.fixture
    def scheduler_mock(self) -> MagicMock:
        s = MagicMock()
        s.notify_change = MagicMock()
        return s

    @pytest.fixture
    def manager(self, store: InMemoryCronStore, scheduler_mock: MagicMock) -> CronManager:
        return CronManager(store=store, scheduler=scheduler_mock, shell_enabled=True)

    @pytest.mark.asyncio
    async def test_agent_job_full_lifecycle(
        self,
        manager: CronManager,
        executor: JobExecutor,
        agent_runner: FakeAgentRunner,
        store: InMemoryCronStore,
        delivery: FakeDelivery,
    ) -> None:
        job = await manager.create_job(
            user_id="user-1",
            name="Daily Report",
            job_type=JobType.AGENT,
            schedule=Schedule(kind=ScheduleKind.CRON, expr="0 9 * * *"),
            prompt="Generate daily report",
            model="gpt-4",
        )
        assert job.status == JobStatus.ACTIVE
        assert job.next_run_at is not None

        persisted = await store.get_job(job.id)
        assert persisted is not None
        assert persisted.name == "Daily Report"

        await executor.run_and_record(job, agent_runner)

        assert agent_runner.call_count == 1
        assert len(delivery.deliveries) == 1
        _delivered_job, delivered_result = delivery.deliveries[0]
        assert delivered_result.success is True
        assert "Agent completed task" in delivered_result.output

        runs = await store.list_runs(job.id)
        assert len(runs) == 1
        assert runs[0].status == RunStatus.OK
        assert runs[0].job_id == job.id

        updated_job = await store.get_job(job.id)
        assert updated_job is not None
        assert updated_job.last_status == RunStatus.OK
        assert updated_job.consecutive_failures == 0

    @pytest.mark.asyncio
    async def test_shell_job_lifecycle(
        self,
        manager: CronManager,
        executor: JobExecutor,
        store: InMemoryCronStore,
        delivery: FakeDelivery,
    ) -> None:
        shell_runner = FakeShellRunner(output="disk usage: 42%")

        job = await manager.create_job(
            user_id="user-1",
            name="Disk Check",
            job_type=JobType.SHELL,
            schedule=Schedule(kind=ScheduleKind.INTERVAL, interval_ms=3600000),
            command="df -h",
        )

        await executor.run_and_record(job, shell_runner)

        assert shell_runner.call_count == 1
        runs = await store.list_runs(job.id)
        assert len(runs) == 1
        assert runs[0].status == RunStatus.OK
        assert "disk usage" in (runs[0].output or "")

    @pytest.mark.asyncio
    async def test_once_job_auto_delete(
        self,
        manager: CronManager,
        executor: JobExecutor,
        agent_runner: FakeAgentRunner,
        store: InMemoryCronStore,
    ) -> None:
        run_at = datetime.now(UTC) + timedelta(minutes=5)
        job = await manager.create_job(
            user_id="user-1",
            name="One-time Task",
            job_type=JobType.AGENT,
            schedule=Schedule(kind=ScheduleKind.ONCE, run_at=run_at),
            prompt="Do this once",
        )
        assert job.delete_after_run is True

        await executor.run_and_record(job, agent_runner)

        deleted_job = await store.get_job(job.id)
        assert deleted_job is None


# ---------------------------------------------------------------------------
# Scenario 2: Failure handling and auto-pause
# ---------------------------------------------------------------------------


class TestFailureHandling:
    @pytest.fixture
    def store(self) -> InMemoryCronStore:
        return InMemoryCronStore()

    @pytest.fixture
    def delivery(self) -> FakeDelivery:
        return FakeDelivery()

    @pytest.fixture
    def executor(self, store: InMemoryCronStore, delivery: FakeDelivery) -> JobExecutor:
        return JobExecutor(store=store, delivery=delivery)

    @pytest.fixture
    def scheduler_mock(self) -> MagicMock:
        s = MagicMock()
        s.notify_change = MagicMock()
        return s

    @pytest.fixture
    def manager(self, store: InMemoryCronStore, scheduler_mock: MagicMock) -> CronManager:
        return CronManager(store=store, scheduler=scheduler_mock, shell_enabled=True)

    @pytest.mark.asyncio
    async def test_consecutive_failures_auto_pause(
        self,
        manager: CronManager,
        executor: JobExecutor,
        store: InMemoryCronStore,
    ) -> None:
        """After max_retries+1 consecutive failures, job should auto-pause."""
        failing_runner = FakeAgentRunner(success=False)

        job = await manager.create_job(
            user_id="user-1",
            name="Flaky Job",
            job_type=JobType.AGENT,
            schedule=Schedule(kind=ScheduleKind.CRON, expr="*/5 * * * *"),
            prompt="do something",
            max_retries=2,
        )

        for _i in range(3):
            await executor.run_and_record(job, failing_runner)

        updated = await store.get_job(job.id)
        assert updated is not None
        assert updated.status == JobStatus.PAUSED
        assert updated.consecutive_failures == 3

    @pytest.mark.asyncio
    async def test_success_resets_failures(
        self,
        manager: CronManager,
        executor: JobExecutor,
        store: InMemoryCronStore,
    ) -> None:
        job = await manager.create_job(
            user_id="user-1",
            name="Recovery Job",
            job_type=JobType.AGENT,
            schedule=Schedule(kind=ScheduleKind.CRON, expr="0 * * * *"),
            prompt="do something",
            max_retries=5,
        )

        failing_runner = FakeAgentRunner(success=False)
        await executor.run_and_record(job, failing_runner)
        await executor.run_and_record(job, failing_runner)

        mid = await store.get_job(job.id)
        assert mid is not None
        assert mid.consecutive_failures == 2

        success_runner = FakeAgentRunner(success=True)
        await executor.run_and_record(job, success_runner)

        recovered = await store.get_job(job.id)
        assert recovered is not None
        assert recovered.consecutive_failures == 0
        assert recovered.last_status == RunStatus.OK


# ---------------------------------------------------------------------------
# Scenario 3: CRUD operations via CronManager
# ---------------------------------------------------------------------------


class TestCRUDOperations:
    @pytest.fixture
    def store(self) -> InMemoryCronStore:
        return InMemoryCronStore()

    @pytest.fixture
    def scheduler_mock(self) -> MagicMock:
        s = MagicMock()
        s.notify_change = MagicMock()
        return s

    @pytest.fixture
    def manager(self, store: InMemoryCronStore, scheduler_mock: MagicMock) -> CronManager:
        return CronManager(store=store, scheduler=scheduler_mock, shell_enabled=True)

    @pytest.mark.asyncio
    async def test_create_list_get_delete(self, manager: CronManager) -> None:
        job = await manager.create_job(
            user_id="user-1",
            name="Test CRUD",
            job_type=JobType.AGENT,
            schedule=Schedule(kind=ScheduleKind.CRON, expr="0 * * * *"),
            prompt="test",
        )

        jobs = await manager.list_jobs("user-1")
        assert len(jobs) == 1
        assert jobs[0].id == job.id

        fetched = await manager.get_job(job.id, "user-1")
        assert fetched is not None
        assert fetched.name == "Test CRUD"

        assert await manager.get_job(job.id, "user-2") is None

        assert await manager.delete_job(job.id, "user-1") is True
        assert await manager.get_job(job.id, "user-1") is None

    @pytest.mark.asyncio
    async def test_pause_and_resume(self, manager: CronManager) -> None:
        job = await manager.create_job(
            user_id="user-1",
            name="Pausable",
            job_type=JobType.AGENT,
            schedule=Schedule(kind=ScheduleKind.CRON, expr="0 * * * *"),
            prompt="test",
        )

        paused = await manager.pause_job(job.id, "user-1")
        assert paused is not None
        assert paused.status == JobStatus.PAUSED

        resumed = await manager.resume_job(job.id, "user-1")
        assert resumed is not None
        assert resumed.status == JobStatus.ACTIVE
        assert resumed.next_run_at is not None

    @pytest.mark.asyncio
    async def test_trigger_now(self, manager: CronManager) -> None:
        job = await manager.create_job(
            user_id="user-1",
            name="Triggerable",
            job_type=JobType.AGENT,
            schedule=Schedule(kind=ScheduleKind.CRON, expr="0 0 1 1 *"),
            prompt="test",
        )

        triggered = await manager.trigger_now(job.id, "user-1")
        assert triggered is True


# ---------------------------------------------------------------------------
# Scenario 4: Delivery edge cases
# ---------------------------------------------------------------------------


class TestDeliveryEdgeCases:
    @pytest.fixture
    def store(self) -> InMemoryCronStore:
        return InMemoryCronStore()

    @pytest.fixture
    def delivery(self) -> FakeDelivery:
        return FakeDelivery()

    @pytest.fixture
    def executor(self, store: InMemoryCronStore, delivery: FakeDelivery) -> JobExecutor:
        return JobExecutor(store=store, delivery=delivery)

    @pytest.fixture
    def scheduler_mock(self) -> MagicMock:
        s = MagicMock()
        s.notify_change = MagicMock()
        return s

    @pytest.fixture
    def manager(self, store: InMemoryCronStore, scheduler_mock: MagicMock) -> CronManager:
        return CronManager(store=store, scheduler=scheduler_mock, shell_enabled=True)

    @pytest.mark.asyncio
    async def test_silent_response_skips_delivery(
        self,
        manager: CronManager,
        executor: JobExecutor,
        delivery: FakeDelivery,
    ) -> None:
        job = await manager.create_job(
            user_id="user-1",
            name="Silent Job",
            job_type=JobType.AGENT,
            schedule=Schedule(kind=ScheduleKind.CRON, expr="0 * * * *"),
            prompt="check something quietly",
        )

        silent_runner = FakeAgentRunner(output="[SILENT]")
        await executor.run_and_record(job, silent_runner)

        assert len(delivery.deliveries) == 0

    @pytest.mark.asyncio
    async def test_none_channel_skips_delivery(
        self,
        manager: CronManager,
        executor: JobExecutor,
        delivery: FakeDelivery,
    ) -> None:
        job = await manager.create_job(
            user_id="user-1",
            name="No Delivery",
            job_type=JobType.AGENT,
            schedule=Schedule(kind=ScheduleKind.CRON, expr="0 * * * *"),
            prompt="internal task",
            delivery=DeliveryConfig(channel="none"),
        )

        runner = FakeAgentRunner(output="done")
        await executor.run_and_record(job, runner)

        assert len(delivery.deliveries) == 0

    @pytest.mark.asyncio
    async def test_dedup_skips_duplicate(
        self,
        manager: CronManager,
        executor: JobExecutor,
        delivery: FakeDelivery,
    ) -> None:
        job = await manager.create_job(
            user_id="user-1",
            name="Dedup Job",
            job_type=JobType.AGENT,
            schedule=Schedule(kind=ScheduleKind.CRON, expr="0 * * * *"),
            prompt="check status",
            deduplicate=True,
        )

        runner = FakeAgentRunner(output="status: OK")
        await executor.run_and_record(job, runner)
        assert len(delivery.deliveries) == 1

        await executor.run_and_record(job, runner)
        assert len(delivery.deliveries) == 1


# ---------------------------------------------------------------------------
# Scenario 5: Scheduler _on_tick integration
# ---------------------------------------------------------------------------


class TestSchedulerOnTick:
    """Test scheduler's _on_tick dispatching with real store."""

    @pytest.mark.asyncio
    async def test_on_tick_dispatches_due_jobs(self) -> None:
        store = InMemoryCronStore()
        delivery = FakeDelivery()
        agent_runner = FakeAgentRunner()

        scheduler = CronScheduler(
            store=store,
            runners={JobType.AGENT: agent_runner},
            delivery=delivery,
            config=CronConfig(max_concurrent=5, max_per_user=3),
        )

        now = datetime.now(UTC)
        job = CronJob(
            id="tick-job-1",
            user_id="user-1",
            name="Due Job",
            job_type=JobType.AGENT,
            schedule=Schedule(kind=ScheduleKind.CRON, expr="* * * * *"),
            status=JobStatus.ACTIVE,
            prompt="run me",
            next_run_at=now - timedelta(seconds=5),
            delivery=DeliveryConfig(channel="chat"),
        )
        await store.save_job(job)

        scheduler._running = True
        await scheduler._on_tick()

        for _ in range(20):
            await asyncio.sleep(0.1)
            if agent_runner.call_count >= 1:
                break

        await scheduler.stop()

        assert agent_runner.call_count == 1
        runs = await store.list_runs("tick-job-1")
        assert len(runs) == 1
        assert runs[0].status == RunStatus.OK

    @pytest.mark.asyncio
    async def test_on_tick_skips_past_grace(self) -> None:
        store = InMemoryCronStore()
        delivery = FakeDelivery()
        agent_runner = FakeAgentRunner()

        scheduler = CronScheduler(
            store=store,
            runners={JobType.AGENT: agent_runner},
            delivery=delivery,
        )

        now = datetime.now(UTC)
        job = CronJob(
            id="stale-job",
            user_id="user-1",
            name="Stale Job",
            job_type=JobType.AGENT,
            schedule=Schedule(kind=ScheduleKind.CRON, expr="0 * * * *"),
            status=JobStatus.ACTIVE,
            prompt="run me",
            next_run_at=now - timedelta(seconds=600),
            misfire_grace_seconds=60,
            delivery=DeliveryConfig(channel="chat"),
        )
        await store.save_job(job)

        scheduler._running = True
        await scheduler._on_tick()
        await asyncio.sleep(0.2)

        assert agent_runner.call_count == 0


# ---------------------------------------------------------------------------
# Scenario 6: Run record integrity chain
# ---------------------------------------------------------------------------


class TestIntegrityChain:
    @pytest.fixture
    def store(self) -> InMemoryCronStore:
        return InMemoryCronStore()

    @pytest.fixture
    def delivery(self) -> FakeDelivery:
        return FakeDelivery()

    @pytest.fixture
    def executor(self, store: InMemoryCronStore, delivery: FakeDelivery) -> JobExecutor:
        return JobExecutor(store=store, delivery=delivery)

    @pytest.mark.asyncio
    async def test_integrity_chain_builds_correctly(
        self,
        executor: JobExecutor,
        store: InMemoryCronStore,
    ) -> None:
        job = CronJob(
            id="chain-job",
            user_id="user-1",
            name="Chain Test",
            job_type=JobType.AGENT,
            schedule=Schedule(kind=ScheduleKind.CRON, expr="0 * * * *"),
            prompt="test",
            delivery=DeliveryConfig(channel="chat"),
        )
        await store.save_job(job)

        runner = FakeAgentRunner()
        for _ in range(3):
            await executor.run_and_record(job, runner)

        runs = await store.list_runs("chain-job", limit=10)
        assert len(runs) == 3

        for run in runs:
            assert run.integrity_hash is not None
            assert run.prev_hash is not None
