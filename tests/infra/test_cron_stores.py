"""Unit tests for InMemoryCronStore."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from myrm_agent_harness.infra.incremental.types import MonitorState
from myrm_agent_harness.toolkits.cron.stores import InMemoryCronStore
from myrm_agent_harness.toolkits.cron.types import (
    CronJob,
    CronRunRecord,
    DeliveryConfig,
    JobStatus,
    JobType,
    RunStatus,
    Schedule,
    ScheduleKind,
)

_NOW = datetime(2026, 3, 29, 12, 0, 0, tzinfo=UTC)


def _job(
    job_id: str = "j1",
    user_id: str = "u1",
    status: JobStatus = JobStatus.ACTIVE,
    next_run_at: datetime | None = None,
) -> CronJob:
    return CronJob(
        id=job_id,
        user_id=user_id,
        name=f"test-{job_id}",
        job_type=JobType.SHELL,
        command="echo hi",
        schedule=Schedule(kind=ScheduleKind.INTERVAL, interval_ms=60_000),
        delivery=DeliveryConfig(channel="none"),
        status=status,
        next_run_at=next_run_at,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _run(
    run_id: str = "r1",
    job_id: str = "j1",
    started_at: datetime | None = None,
    integrity_hash: str | None = None,
) -> CronRunRecord:
    t = started_at or _NOW
    return CronRunRecord(
        id=run_id,
        job_id=job_id,
        started_at=t,
        finished_at=t + timedelta(seconds=1),
        duration_ms=1000,
        status=RunStatus.OK,
        integrity_hash=integrity_hash,
    )


class TestJobCRUD:
    @pytest.fixture
    async def store(self) -> InMemoryCronStore:
        return InMemoryCronStore()

    async def test_save_and_get(self, store: InMemoryCronStore) -> None:
        job = _job()
        saved = await store.save_job(job)
        assert saved.id == "j1"
        fetched = await store.get_job("j1")
        assert fetched is not None
        assert fetched.id == "j1"

    async def test_get_nonexistent(self, store: InMemoryCronStore) -> None:
        assert await store.get_job("nope") is None

    async def test_delete(self, store: InMemoryCronStore) -> None:
        await store.save_job(_job())
        assert await store.delete_job("j1") is True
        assert await store.get_job("j1") is None
        assert await store.delete_job("j1") is False

    async def test_list_all(self, store: InMemoryCronStore) -> None:
        await store.save_job(_job("j1"))
        await store.save_job(_job("j2"))
        jobs = await store.list_jobs()
        assert len(jobs) == 2

    async def test_list_by_user(self, store: InMemoryCronStore) -> None:
        await store.save_job(_job("j1", user_id="u1"))
        await store.save_job(_job("j2", user_id="u2"))
        jobs = await store.list_jobs(user_id="u1")
        assert len(jobs) == 1
        assert jobs[0].user_id == "u1"

    async def test_list_due_before(self, store: InMemoryCronStore) -> None:
        past = _NOW - timedelta(hours=1)
        future = _NOW + timedelta(hours=1)
        await store.save_job(_job("j1", next_run_at=past))
        await store.save_job(_job("j2", next_run_at=future))
        due = await store.list_jobs(due_before=_NOW)
        assert len(due) == 1
        assert due[0].id == "j1"

    async def test_list_pagination(self, store: InMemoryCronStore) -> None:
        for i in range(5):
            await store.save_job(_job(f"j{i}"))
        page = await store.list_jobs(limit=2, offset=1)
        assert len(page) == 2

    async def test_count_jobs(self, store: InMemoryCronStore) -> None:
        await store.save_job(_job("j1", user_id="u1"))
        await store.save_job(_job("j2", user_id="u2"))
        assert await store.count_jobs() == 2
        assert await store.count_jobs(user_id="u1") == 1

    async def test_earliest_next_run(self, store: InMemoryCronStore) -> None:
        t1 = _NOW + timedelta(hours=1)
        t2 = _NOW + timedelta(hours=2)
        await store.save_job(_job("j1", next_run_at=t1))
        await store.save_job(_job("j2", next_run_at=t2))
        assert await store.earliest_next_run() == t1

    async def test_earliest_next_run_empty(self, store: InMemoryCronStore) -> None:
        assert await store.earliest_next_run() is None

    async def test_claim_due(self, store: InMemoryCronStore) -> None:
        await store.save_job(_job("j1", next_run_at=_NOW))
        await store.claim_due(["j1"])
        job = await store.get_job("j1")
        assert job is not None
        assert job.next_run_at is None

    async def test_list_orphaned_active(self, store: InMemoryCronStore) -> None:
        await store.save_job(_job("j1", next_run_at=None))
        await store.save_job(_job("j2", next_run_at=_NOW))
        orphans = await store.list_orphaned_active()
        assert len(orphans) == 1
        assert orphans[0].id == "j1"

    async def test_deepcopy_isolation(self, store: InMemoryCronStore) -> None:
        await store.save_job(_job("j1"))
        fetched = await store.get_job("j1")
        assert fetched is not None
        fetched.name = "mutated"
        original = await store.get_job("j1")
        assert original is not None
        assert original.name == "test-j1"


class TestRunRecords:
    @pytest.fixture
    async def store(self) -> InMemoryCronStore:
        return InMemoryCronStore()

    async def test_save_and_list_runs(self, store: InMemoryCronStore) -> None:
        await store.save_run(_run("r1", "j1"))
        await store.save_run(_run("r2", "j1"))
        await store.save_run(_run("r3", "j2"))
        runs = await store.list_runs("j1")
        assert len(runs) == 2

    async def test_list_runs_pagination(self, store: InMemoryCronStore) -> None:
        for i in range(5):
            await store.save_run(_run(f"r{i}", "j1", started_at=_NOW + timedelta(minutes=i)))
        runs = await store.list_runs("j1", limit=2, offset=1)
        assert len(runs) == 2

    async def test_count_runs(self, store: InMemoryCronStore) -> None:
        await store.save_run(_run("r1", "j1"))
        await store.save_run(_run("r2", "j2"))
        assert await store.count_runs() == 2
        assert await store.count_runs(job_id="j1") == 1

    async def test_purge_old_runs(self, store: InMemoryCronStore) -> None:
        old = _NOW - timedelta(days=60)
        await store.save_run(_run("r1", "j1", started_at=old))
        await store.save_run(_run("r2", "j1", started_at=_NOW))
        deleted = await store.purge_old_runs(before=_NOW - timedelta(days=30))
        assert deleted == 1
        assert await store.count_runs() == 1

    async def test_get_latest_integrity_hash(self, store: InMemoryCronStore) -> None:
        await store.save_run(_run("r1", "j1", started_at=_NOW, integrity_hash="hash1"))
        await store.save_run(_run("r2", "j1", started_at=_NOW + timedelta(minutes=1), integrity_hash="hash2"))
        assert await store.get_latest_integrity_hash("j1") == "hash2"
        assert await store.get_latest_integrity_hash("j999") is None

    async def test_delete_job_cascade(self, store: InMemoryCronStore) -> None:
        await store.save_job(_job("j1"))
        await store.save_run(_run("r1", "j1"))
        await store.save_monitor_state(MonitorState(job_id="j1", monitor_type="set", data={}))
        assert await store.delete_job_cascade("j1") is True
        assert await store.get_job("j1") is None
        assert await store.count_runs(job_id="j1") == 0
        assert await store.get_monitor_state("j1") is None


class TestMonitorState:
    @pytest.fixture
    async def store(self) -> InMemoryCronStore:
        return InMemoryCronStore()

    async def test_save_and_get(self, store: InMemoryCronStore) -> None:
        state = MonitorState(job_id="j1", monitor_type="set", data={"seen": ["a"]})
        await store.save_monitor_state(state)
        fetched = await store.get_monitor_state("j1")
        assert fetched is not None
        assert fetched.data == {"seen": ["a"]}

    async def test_get_nonexistent(self, store: InMemoryCronStore) -> None:
        assert await store.get_monitor_state("nope") is None

    async def test_delete(self, store: InMemoryCronStore) -> None:
        await store.save_monitor_state(MonitorState(job_id="j1", monitor_type="set", data={}))
        assert await store.delete_monitor_state("j1") is True
        assert await store.delete_monitor_state("j1") is False

    async def test_batch_get(self, store: InMemoryCronStore) -> None:
        await store.save_monitor_state(MonitorState(job_id="j1", monitor_type="set", data={"seen": ["a"]}))
        await store.save_monitor_state(MonitorState(job_id="j2", monitor_type="hash", data={"last_hash": "x"}))
        result = await store.batch_get_monitor_states(["j1", "j2", "j3"])
        assert len(result) == 2
        assert "j1" in result
        assert "j2" in result
