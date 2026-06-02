"""InMemoryCronStore direct unit tests — covers CRUD, filtering, monitor state.

Targets the uncovered branches in stores.py (monitor CRUD, count_jobs global,
list_runs with status filter, count_runs, purge_old_runs, list_orphaned_active).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from myrm_agent_harness.infra.incremental.types import MonitorState
from myrm_agent_harness.toolkits.cron.stores import InMemoryCronStore
from myrm_agent_harness.toolkits.cron.types import (
    CronJob,
    CronRunRecord,
    JobStatus,
    JobType,
    RunStatus,
    Schedule,
    ScheduleKind,
)

_SENTINEL = object()


def _make_job(
    job_id: str = "j1",
    user_id: str = "u1",
    status: JobStatus = JobStatus.ACTIVE,
    next_run_at: datetime | None | object = _SENTINEL,
) -> CronJob:
    return CronJob(
        id=job_id,
        user_id=user_id,
        name=f"Job {job_id}",
        job_type=JobType.AGENT,
        schedule=Schedule(kind=ScheduleKind.CRON, expr="0 * * * *"),
        status=status,
        prompt="test prompt",
        next_run_at=datetime.now(UTC) if next_run_at is _SENTINEL else next_run_at,  # type: ignore[arg-type]
    )


def _make_run(
    run_id: str = "r1",
    job_id: str = "j1",
    status: RunStatus = RunStatus.OK,
    started_at: datetime | None = None,
    integrity_hash: str = "",
) -> CronRunRecord:
    start = started_at or datetime.now(UTC)
    return CronRunRecord(
        id=run_id,
        job_id=job_id,
        started_at=start,
        finished_at=start + timedelta(seconds=10),
        duration_ms=10_000,
        status=status,
        integrity_hash=integrity_hash,
    )


@pytest.fixture()
def store() -> InMemoryCronStore:
    return InMemoryCronStore()


class TestCountJobs:
    @pytest.mark.asyncio
    async def test_global_count(self, store: InMemoryCronStore):
        await store.save_job(_make_job("j1", "u1"))
        await store.save_job(_make_job("j2", "u2"))
        assert await store.count_jobs() == 2

    @pytest.mark.asyncio
    async def test_per_user_count(self, store: InMemoryCronStore):
        await store.save_job(_make_job("j1", "u1"))
        await store.save_job(_make_job("j2", "u1"))
        await store.save_job(_make_job("j3", "u2"))
        assert await store.count_jobs(user_id="u1") == 2
        assert await store.count_jobs(user_id="u2") == 1


class TestListJobsFilters:
    @pytest.mark.asyncio
    async def test_name_filter(self, store: InMemoryCronStore):
        j1 = _make_job("j1")
        j1.name = "Daily Backup"
        j2 = _make_job("j2")
        j2.name = "Weekly Report"
        await store.save_job(j1)
        await store.save_job(j2)

        result = await store.list_jobs(name_filter="backup")
        assert len(result) == 1
        assert result[0].name == "Daily Backup"

    @pytest.mark.asyncio
    async def test_offset_and_limit(self, store: InMemoryCronStore):
        for i in range(5):
            await store.save_job(_make_job(f"j{i}"))
        result = await store.list_jobs(offset=2, limit=2)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_due_before_filter(self, store: InMemoryCronStore):
        now = datetime.now(UTC)
        j1 = _make_job("j1", next_run_at=now - timedelta(hours=1))
        j2 = _make_job("j2", next_run_at=now + timedelta(hours=1))
        await store.save_job(j1)
        await store.save_job(j2)

        result = await store.list_jobs(due_before=now)
        assert len(result) == 1
        assert result[0].id == "j1"


class TestListRunsAndCount:
    @pytest.mark.asyncio
    async def test_list_runs_with_status_filter(self, store: InMemoryCronStore):
        await store.save_run(_make_run("r1", status=RunStatus.OK))
        await store.save_run(_make_run("r2", status=RunStatus.ERROR))
        await store.save_run(_make_run("r3", status=RunStatus.OK))

        ok_runs = await store.list_runs(status="ok")
        assert len(ok_runs) == 2

        err_runs = await store.list_runs(status="error")
        assert len(err_runs) == 1

    @pytest.mark.asyncio
    async def test_count_runs_global(self, store: InMemoryCronStore):
        await store.save_run(_make_run("r1", "j1"))
        await store.save_run(_make_run("r2", "j1"))
        await store.save_run(_make_run("r3", "j2"))
        assert await store.count_runs() == 3

    @pytest.mark.asyncio
    async def test_count_runs_by_job(self, store: InMemoryCronStore):
        await store.save_run(_make_run("r1", "j1"))
        await store.save_run(_make_run("r2", "j1"))
        await store.save_run(_make_run("r3", "j2"))
        assert await store.count_runs(job_id="j1") == 2

    @pytest.mark.asyncio
    async def test_count_runs_by_status(self, store: InMemoryCronStore):
        await store.save_run(_make_run("r1", status=RunStatus.OK))
        await store.save_run(_make_run("r2", status=RunStatus.ERROR))
        assert await store.count_runs(status="ok") == 1
        assert await store.count_runs(status="error") == 1


class TestOrphanedAndPurge:
    @pytest.mark.asyncio
    async def test_list_orphaned_active(self, store: InMemoryCronStore):
        j1 = _make_job("j1", next_run_at=None)
        j2 = _make_job("j2", next_run_at=datetime.now(UTC))
        j3 = _make_job("j3", status=JobStatus.PAUSED, next_run_at=None)
        await store.save_job(j1)
        await store.save_job(j2)
        await store.save_job(j3)

        orphans = await store.list_orphaned_active()
        assert len(orphans) == 1
        assert orphans[0].id == "j1"

    @pytest.mark.asyncio
    async def test_purge_old_runs(self, store: InMemoryCronStore):
        now = datetime.now(UTC)
        old_run = _make_run("r1", started_at=now - timedelta(days=60))
        new_run = _make_run("r2", started_at=now - timedelta(hours=1))
        await store.save_run(old_run)
        await store.save_run(new_run)

        purged = await store.purge_old_runs(before=now - timedelta(days=30))
        assert purged == 1
        remaining = await store.list_runs()
        assert len(remaining) == 1


class TestMonitorStateCRUD:
    @pytest.mark.asyncio
    async def test_save_and_get(self, store: InMemoryCronStore):
        state = MonitorState(job_id="j1", monitor_type="set", data={"seen": ["a"]})
        await store.save_monitor_state(state)

        loaded = await store.get_monitor_state("j1")
        assert loaded is not None
        assert loaded.job_id == "j1"
        assert loaded.data == {"seen": ["a"]}

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, store: InMemoryCronStore):
        assert await store.get_monitor_state("missing") is None

    @pytest.mark.asyncio
    async def test_delete(self, store: InMemoryCronStore):
        state = MonitorState(job_id="j1", monitor_type="set", data={})
        await store.save_monitor_state(state)

        assert await store.delete_monitor_state("j1") is True
        assert await store.get_monitor_state("j1") is None
        assert await store.delete_monitor_state("j1") is False

    @pytest.mark.asyncio
    async def test_batch_get(self, store: InMemoryCronStore):
        s1 = MonitorState(job_id="j1", monitor_type="set", data={"k": "v1"})
        s2 = MonitorState(job_id="j2", monitor_type="hash", data={"k": "v2"})
        await store.save_monitor_state(s1)
        await store.save_monitor_state(s2)

        result = await store.batch_get_monitor_states(["j1", "j2", "j3"])
        assert len(result) == 2
        assert "j1" in result
        assert "j2" in result
        assert "j3" not in result

    @pytest.mark.asyncio
    async def test_deep_copy_isolation(self, store: InMemoryCronStore):
        """Verify mutations on returned state don't affect stored state."""
        state = MonitorState(job_id="j1", monitor_type="set", data={"seen": ["a"]})
        await store.save_monitor_state(state)

        loaded = await store.get_monitor_state("j1")
        assert loaded is not None
        loaded.data["seen"] = ["a", "b", "c"]

        reloaded = await store.get_monitor_state("j1")
        assert reloaded is not None
        assert reloaded.data == {"seen": ["a"]}


class TestDeleteJobCascade:
    @pytest.mark.asyncio
    async def test_cascade_removes_runs_and_monitors(self, store: InMemoryCronStore):
        await store.save_job(_make_job("j1"))
        await store.save_run(_make_run("r1", "j1"))
        await store.save_run(_make_run("r2", "j1"))
        await store.save_monitor_state(MonitorState(job_id="j1", monitor_type="set", data={}))

        assert await store.delete_job_cascade("j1") is True
        assert await store.get_job("j1") is None
        assert await store.list_runs(job_id="j1") == []
        assert await store.get_monitor_state("j1") is None

    @pytest.mark.asyncio
    async def test_cascade_nonexistent_returns_false(self, store: InMemoryCronStore):
        assert await store.delete_job_cascade("missing") is False
