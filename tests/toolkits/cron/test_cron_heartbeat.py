"""Unit tests for the Heartbeat convenience layer over CronManager."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.toolkits.cron.heartbeat import (
    _DEFAULT_INTERVAL_MS,
    _DEFAULT_PROMPT,
    _DEFAULT_TIMEOUT,
    HEARTBEAT_JOB_NAME,
    HeartbeatStatus,
    disable_heartbeat,
    enable_heartbeat,
    get_heartbeat_status,
)
from myrm_agent_harness.toolkits.cron.types import (
    CronJob,
    DeliveryConfig,
    JobStatus,
    JobType,
    Schedule,
    ScheduleKind,
    SessionTarget,
)


def _make_manager() -> MagicMock:
    mgr = MagicMock()
    mgr.list_jobs = AsyncMock(return_value=[])
    mgr.create_job = AsyncMock()
    mgr.update_job = AsyncMock()
    mgr.pause_job = AsyncMock()
    return mgr


def _make_heartbeat_job(
    *,
    status: JobStatus = JobStatus.ACTIVE,
    interval_ms: int = _DEFAULT_INTERVAL_MS,
    prompt: str | None = _DEFAULT_PROMPT,
    model: str | None = None,
) -> CronJob:
    return CronJob(
        id="hb-1",
        user_id="owner-1",
        name=HEARTBEAT_JOB_NAME,
        job_type=JobType.AGENT,
        schedule=Schedule(kind=ScheduleKind.INTERVAL, interval_ms=interval_ms),
        status=status,
        prompt=prompt,
        model=model,
        delivery=DeliveryConfig(channel="chat"),
        session_target=SessionTarget.ISOLATED,
        timeout_seconds=_DEFAULT_TIMEOUT,
        deduplicate=True,
    )


# ---------------------------------------------------------------------------
# enable_heartbeat
# ---------------------------------------------------------------------------


class TestEnableHeartbeat:
    @pytest.mark.asyncio
    async def test_create_new(self):
        mgr = _make_manager()
        created = _make_heartbeat_job()
        mgr.create_job = AsyncMock(return_value=created)

        result = await enable_heartbeat(mgr, "owner-1")

        assert result is created
        mgr.create_job.assert_awaited_once()
        call_kwargs = mgr.create_job.call_args[1]
        assert call_kwargs["user_id"] == "owner-1"
        assert call_kwargs["name"] == HEARTBEAT_JOB_NAME
        assert call_kwargs["job_type"] == JobType.AGENT
        assert call_kwargs["prompt"] == _DEFAULT_PROMPT
        assert call_kwargs["timeout_seconds"] == _DEFAULT_TIMEOUT
        assert call_kwargs["deduplicate"] is True
        assert call_kwargs["session_target"] == SessionTarget.ISOLATED

    @pytest.mark.asyncio
    async def test_create_with_custom_params(self):
        mgr = _make_manager()
        created = _make_heartbeat_job(interval_ms=60_000, prompt="custom", model="gpt-4o-mini")
        mgr.create_job = AsyncMock(return_value=created)

        result = await enable_heartbeat(mgr, "owner-1", interval_ms=60_000, prompt="custom", model="gpt-4o-mini")

        assert result is created
        call_kwargs = mgr.create_job.call_args[1]
        assert call_kwargs["schedule"].interval_ms == 60_000
        assert call_kwargs["prompt"] == "custom"
        assert call_kwargs["model"] == "gpt-4o-mini"

    @pytest.mark.asyncio
    async def test_idempotent_resume_existing(self):
        """When heartbeat already exists, it should update rather than create."""
        existing = _make_heartbeat_job(status=JobStatus.PAUSED)
        mgr = _make_manager()
        mgr.list_jobs = AsyncMock(return_value=[existing])
        updated = _make_heartbeat_job(status=JobStatus.ACTIVE)
        mgr.update_job = AsyncMock(return_value=updated)

        result = await enable_heartbeat(mgr, "owner-1")

        assert result is updated
        mgr.create_job.assert_not_awaited()
        mgr.update_job.assert_awaited_once()
        patch = mgr.update_job.call_args[0][2]
        assert patch.status == JobStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_idempotent_update_returns_none(self):
        """If update_job returns None, fall back to existing job."""
        existing = _make_heartbeat_job()
        mgr = _make_manager()
        mgr.list_jobs = AsyncMock(return_value=[existing])
        mgr.update_job = AsyncMock(return_value=None)

        result = await enable_heartbeat(mgr, "owner-1")

        assert result is existing

    @pytest.mark.asyncio
    async def test_preserves_existing_prompt_when_none_passed(self):
        """Custom prompt in existing job should be preserved."""
        existing = _make_heartbeat_job(prompt="my custom prompt")
        mgr = _make_manager()
        mgr.list_jobs = AsyncMock(return_value=[existing])
        mgr.update_job = AsyncMock(return_value=existing)

        await enable_heartbeat(mgr, "owner-1")

        patch = mgr.update_job.call_args[0][2]
        assert patch.prompt == "my custom prompt"


# ---------------------------------------------------------------------------
# disable_heartbeat
# ---------------------------------------------------------------------------


class TestDisableHeartbeat:
    @pytest.mark.asyncio
    async def test_disable_existing(self):
        existing = _make_heartbeat_job()
        mgr = _make_manager()
        mgr.list_jobs = AsyncMock(return_value=[existing])
        mgr.pause_job = AsyncMock(return_value=existing)

        result = await disable_heartbeat(mgr, "owner-1")

        assert result is True
        mgr.pause_job.assert_awaited_once_with("hb-1", "owner-1")

    @pytest.mark.asyncio
    async def test_disable_nonexistent(self):
        mgr = _make_manager()

        result = await disable_heartbeat(mgr, "owner-1")

        assert result is False
        mgr.pause_job.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_disable_pause_returns_none(self):
        """If pause_job returns None (not found in store), return False."""
        existing = _make_heartbeat_job()
        mgr = _make_manager()
        mgr.list_jobs = AsyncMock(return_value=[existing])
        mgr.pause_job = AsyncMock(return_value=None)

        result = await disable_heartbeat(mgr, "owner-1")

        assert result is False


# ---------------------------------------------------------------------------
# get_heartbeat_status
# ---------------------------------------------------------------------------


class TestGetHeartbeatStatus:
    @pytest.mark.asyncio
    async def test_active_heartbeat(self):
        existing = _make_heartbeat_job(status=JobStatus.ACTIVE)
        mgr = _make_manager()
        mgr.list_jobs = AsyncMock(return_value=[existing])

        status = await get_heartbeat_status(mgr, "owner-1")

        assert isinstance(status, HeartbeatStatus)
        assert status.enabled is True
        assert status.job is existing

    @pytest.mark.asyncio
    async def test_paused_heartbeat(self):
        existing = _make_heartbeat_job(status=JobStatus.PAUSED)
        mgr = _make_manager()
        mgr.list_jobs = AsyncMock(return_value=[existing])

        status = await get_heartbeat_status(mgr, "owner-1")

        assert status.enabled is False
        assert status.job is existing

    @pytest.mark.asyncio
    async def test_no_heartbeat(self):
        mgr = _make_manager()

        status = await get_heartbeat_status(mgr, "owner-1")

        assert status.enabled is False
        assert status.job is None


# ---------------------------------------------------------------------------
# _find_heartbeat (indirectly tested via public functions)
# ---------------------------------------------------------------------------


class TestFindHeartbeat:
    @pytest.mark.asyncio
    async def test_finds_among_other_jobs(self):
        """Heartbeat job should be found even among other jobs."""
        other_job = CronJob(
            id="other-1",
            user_id="owner-1",
            name="Other Job",
            job_type=JobType.AGENT,
            schedule=Schedule(kind=ScheduleKind.CRON, expr="0 * * * *"),
        )
        hb_job = _make_heartbeat_job()
        mgr = _make_manager()
        mgr.list_jobs = AsyncMock(return_value=[other_job, hb_job])

        status = await get_heartbeat_status(mgr, "owner-1")

        assert status.job is hb_job

    @pytest.mark.asyncio
    async def test_uses_correct_limit(self):
        mgr = _make_manager()

        await get_heartbeat_status(mgr, "owner-1")

        mgr.list_jobs.assert_awaited_once_with("owner-1", limit=200)


# ---------------------------------------------------------------------------
# CRON schedule support
# ---------------------------------------------------------------------------


class TestCronSchedule:
    @pytest.mark.asyncio
    async def test_create_with_cron_schedule(self):
        """enable_heartbeat with explicit CRON schedule should use it."""
        mgr = _make_manager()
        cron_sched = Schedule(kind=ScheduleKind.CRON, expr="0 9 * * *", tz="Asia/Shanghai")
        created = CronJob(
            id="hb-cron",
            user_id="owner-1",
            name=HEARTBEAT_JOB_NAME,
            job_type=JobType.AGENT,
            schedule=cron_sched,
            prompt=_DEFAULT_PROMPT,
            delivery=DeliveryConfig(channel="chat"),
            session_target=SessionTarget.ISOLATED,
            timeout_seconds=_DEFAULT_TIMEOUT,
            deduplicate=True,
        )
        mgr.create_job = AsyncMock(return_value=created)

        result = await enable_heartbeat(mgr, "owner-1", schedule=cron_sched)

        assert result is created
        call_kwargs = mgr.create_job.call_args[1]
        assert call_kwargs["schedule"].kind == ScheduleKind.CRON
        assert call_kwargs["schedule"].expr == "0 9 * * *"
        assert call_kwargs["schedule"].tz == "Asia/Shanghai"

    @pytest.mark.asyncio
    async def test_schedule_takes_precedence_over_interval_ms(self):
        """Explicit schedule should override interval_ms."""
        mgr = _make_manager()
        cron_sched = Schedule(kind=ScheduleKind.CRON, expr="0 21 * * *")
        created = _make_heartbeat_job()
        mgr.create_job = AsyncMock(return_value=created)

        await enable_heartbeat(mgr, "owner-1", interval_ms=60_000, schedule=cron_sched)

        call_kwargs = mgr.create_job.call_args[1]
        assert call_kwargs["schedule"].kind == ScheduleKind.CRON
        assert call_kwargs["schedule"].expr == "0 21 * * *"

    @pytest.mark.asyncio
    async def test_update_existing_to_cron(self):
        """Existing interval heartbeat can be updated to cron."""
        existing = _make_heartbeat_job(status=JobStatus.PAUSED)
        mgr = _make_manager()
        mgr.list_jobs = AsyncMock(return_value=[existing])
        updated = _make_heartbeat_job(status=JobStatus.ACTIVE)
        mgr.update_job = AsyncMock(return_value=updated)
        cron_sched = Schedule(kind=ScheduleKind.CRON, expr="30 8 * * 1-5")

        await enable_heartbeat(mgr, "owner-1", schedule=cron_sched)

        patch = mgr.update_job.call_args[0][2]
        assert patch.schedule.kind == ScheduleKind.CRON
        assert patch.schedule.expr == "30 8 * * 1-5"

    @pytest.mark.asyncio
    async def test_no_schedule_falls_back_to_interval(self):
        """Without explicit schedule, interval_ms is used."""
        mgr = _make_manager()
        created = _make_heartbeat_job()
        mgr.create_job = AsyncMock(return_value=created)

        await enable_heartbeat(mgr, "owner-1", interval_ms=3_600_000)

        call_kwargs = mgr.create_job.call_args[1]
        assert call_kwargs["schedule"].kind == ScheduleKind.INTERVAL
        assert call_kwargs["schedule"].interval_ms == 3_600_000


# ---------------------------------------------------------------------------
# agent_id binding
# ---------------------------------------------------------------------------


class TestAgentIdBinding:
    @pytest.mark.asyncio
    async def test_create_with_agent_id(self):
        """New heartbeat with agent_id should pass it to create_job."""
        mgr = _make_manager()
        created = _make_heartbeat_job()
        mgr.create_job = AsyncMock(return_value=created)

        await enable_heartbeat(mgr, "owner-1", agent_id="agent-scout")

        call_kwargs = mgr.create_job.call_args[1]
        assert call_kwargs["agent_id"] == "agent-scout"

    @pytest.mark.asyncio
    async def test_create_without_agent_id(self):
        """New heartbeat without agent_id should pass None."""
        mgr = _make_manager()
        created = _make_heartbeat_job()
        mgr.create_job = AsyncMock(return_value=created)

        await enable_heartbeat(mgr, "owner-1")

        call_kwargs = mgr.create_job.call_args[1]
        assert call_kwargs["agent_id"] is None

    @pytest.mark.asyncio
    async def test_update_with_agent_id(self):
        """Updating existing heartbeat should pass agent_id to patch."""
        existing = _make_heartbeat_job()
        mgr = _make_manager()
        mgr.list_jobs = AsyncMock(return_value=[existing])
        mgr.update_job = AsyncMock(return_value=existing)

        await enable_heartbeat(mgr, "owner-1", agent_id="agent-patrol")

        patch = mgr.update_job.call_args[0][2]
        assert patch.agent_id == "agent-patrol"

    @pytest.mark.asyncio
    async def test_unbind_agent_id(self):
        """agent_id=None should clear binding (empty string in patch)."""
        existing = _make_heartbeat_job()
        mgr = _make_manager()
        mgr.list_jobs = AsyncMock(return_value=[existing])
        mgr.update_job = AsyncMock(return_value=existing)

        await enable_heartbeat(mgr, "owner-1", agent_id=None)

        patch = mgr.update_job.call_args[0][2]
        assert patch.agent_id == ""


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestConstants:
    def test_heartbeat_job_name(self):
        assert HEARTBEAT_JOB_NAME == "__heartbeat__"

    def test_default_interval(self):
        assert _DEFAULT_INTERVAL_MS == 1_800_000  # 30 minutes

    def test_default_timeout(self):
        assert _DEFAULT_TIMEOUT == 120

    def test_default_prompt_contains_silent(self):
        assert "[SILENT]" in _DEFAULT_PROMPT


# ---------------------------------------------------------------------------
# Import from package
# ---------------------------------------------------------------------------


class TestPackageExports:
    def test_importable_from_cron_package(self):
        from myrm_agent_harness.toolkits.cron import (
            HEARTBEAT_JOB_NAME,
            HeartbeatStatus,
        )
        from myrm_agent_harness.toolkits.cron import (
            disable_heartbeat as _disable,
        )
        from myrm_agent_harness.toolkits.cron import (
            enable_heartbeat as _enable,
        )
        from myrm_agent_harness.toolkits.cron import (
            get_heartbeat_status as _get,
        )

        assert HEARTBEAT_JOB_NAME == "__heartbeat__"
        assert HeartbeatStatus is not None
        assert _enable is enable_heartbeat
        assert _disable is disable_heartbeat
        assert _get is get_heartbeat_status
