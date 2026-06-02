"""Tests for cron_manage Agent tool (tools.py).

Validates pause/resume actions, max_fires/expires_after parameters,
list progress display, _parse_expires_after helper, cron execution guard,
schedule builder, delivery resolution, and all action edge cases.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from myrm_agent_harness.toolkits.cron.cron_agent_tools import (
    _parse_context_from,
    _parse_expires_after,
    create_cron_tools,
    enter_cron_execution_context,
    exit_cron_execution_context,
)
from myrm_agent_harness.toolkits.cron.engine.scheduler import CronScheduler
from myrm_agent_harness.toolkits.cron.manager import CronManager
from myrm_agent_harness.toolkits.cron.stores import InMemoryCronStore
from myrm_agent_harness.toolkits.cron.types import (
    CronConfig,
    JobStatus,
    JobType,
    Schedule,
    ScheduleKind,
)

USER_ID = "test-user"


class FakeDelivery:
    async def deliver(self, job, result):
        pass


@pytest.fixture
def store() -> InMemoryCronStore:
    return InMemoryCronStore()


@pytest.fixture
def scheduler(store: InMemoryCronStore) -> CronScheduler:
    return CronScheduler(
        store=store,
        runners={},
        delivery=FakeDelivery(),
        config=CronConfig(),
    )


@pytest.fixture
def manager(store: InMemoryCronStore, scheduler: CronScheduler) -> CronManager:
    return CronManager(store, scheduler, shell_enabled=True)


@pytest.fixture
def tool(manager: CronManager):
    tools = create_cron_tools(manager, USER_ID, current_model="test-model")
    return tools[0]


# ---------------------------------------------------------------------------
# _parse_expires_after
# ---------------------------------------------------------------------------


class TestParseExpiresAfter:
    def test_empty_returns_none(self) -> None:
        assert _parse_expires_after("") is None
        assert _parse_expires_after("  ") is None

    def test_days(self) -> None:
        result = _parse_expires_after("3d")
        assert result is not None
        assert (result - datetime.now(UTC)).days in (2, 3)

    def test_weeks(self) -> None:
        result = _parse_expires_after("2w")
        assert result is not None
        assert (result - datetime.now(UTC)).days in (13, 14)

    def test_months(self) -> None:
        result = _parse_expires_after("3m")
        assert result is not None
        assert (result - datetime.now(UTC)).days in (89, 90)

    def test_iso_datetime(self) -> None:
        result = _parse_expires_after("2030-01-01T00:00:00")
        assert result is not None
        assert result.year == 2030
        assert result.tzinfo is not None

    def test_iso_datetime_with_tz(self) -> None:
        result = _parse_expires_after("2030-06-15T12:00:00+08:00")
        assert result is not None
        assert result.year == 2030

    def test_invalid_raises(self) -> None:
        with pytest.raises((ValueError, TypeError)):
            _parse_expires_after("invalid-date")


# ---------------------------------------------------------------------------
# Pause / Resume actions
# ---------------------------------------------------------------------------


class TestPauseResume:
    @pytest.mark.asyncio
    async def test_pause_active_job(self, tool, manager: CronManager) -> None:
        job = await manager.create_job(
            user_id=USER_ID,
            name="test-job",
            job_type=JobType.AGENT,
            schedule=Schedule(kind=ScheduleKind.INTERVAL, interval_ms=300_000),
            prompt="check something",
        )
        result = await tool.ainvoke({"action": "pause", "job_id": job.id})
        parsed = json.loads(result)
        assert parsed["status"] == "success"
        assert parsed["action"] == "pause"
        assert parsed["job_id"] == job.id

        updated = await manager.get_job(job.id, USER_ID)
        assert updated is not None
        assert updated.status == JobStatus.PAUSED

    @pytest.mark.asyncio
    async def test_resume_paused_job(self, tool, manager: CronManager) -> None:
        job = await manager.create_job(
            user_id=USER_ID,
            name="test-job",
            job_type=JobType.AGENT,
            schedule=Schedule(kind=ScheduleKind.INTERVAL, interval_ms=300_000),
            prompt="check something",
        )
        await manager.pause_job(job.id, USER_ID)

        result = await tool.ainvoke({"action": "resume", "job_id": job.id})
        parsed = json.loads(result)
        assert parsed["status"] == "success"
        assert parsed["action"] == "resume"
        assert "next_run" in parsed

        updated = await manager.get_job(job.id, USER_ID)
        assert updated is not None
        assert updated.status == JobStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_pause_missing_job_id(self, tool) -> None:
        result = await tool.ainvoke({"action": "pause"})
        assert "job_id required" in result

    @pytest.mark.asyncio
    async def test_resume_missing_job_id(self, tool) -> None:
        result = await tool.ainvoke({"action": "resume"})
        assert "job_id required" in result

    @pytest.mark.asyncio
    async def test_pause_nonexistent_job(self, tool) -> None:
        result = await tool.ainvoke({"action": "pause", "job_id": "nonexistent"})
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_resume_nonexistent_job(self, tool) -> None:
        result = await tool.ainvoke({"action": "resume", "job_id": "nonexistent"})
        assert "not found" in result


# ---------------------------------------------------------------------------
# max_fires / expires_after in add
# ---------------------------------------------------------------------------


class TestAddWithLimits:
    @pytest.mark.asyncio
    async def test_add_with_max_fires(self, tool, manager: CronManager) -> None:
        result = await tool.ainvoke(
            {
                "action": "add",
                "prompt": "check stock price",
                "every_minutes": 30,
                "recurring_confirmed": True,
                "max_fires": 100,
            }
        )
        parsed = json.loads(result)
        assert parsed["status"] == "success"
        assert parsed["max_fires"] == 100

        job = await manager.get_job(parsed["job_id"], USER_ID)
        assert job is not None
        assert job.max_fires == 100

    @pytest.mark.asyncio
    async def test_add_with_expires_after_duration(self, tool, manager: CronManager) -> None:
        result = await tool.ainvoke(
            {
                "action": "add",
                "prompt": "monitor air quality",
                "every_minutes": 60,
                "recurring_confirmed": True,
                "expires_after": "7d",
            }
        )
        parsed = json.loads(result)
        assert parsed["status"] == "success"
        assert "expires_at" in parsed

        job = await manager.get_job(parsed["job_id"], USER_ID)
        assert job is not None
        assert job.expires_at is not None
        assert (job.expires_at - datetime.now(UTC)).days in (6, 7)

    @pytest.mark.asyncio
    async def test_add_with_expires_after_iso(self, tool, manager: CronManager) -> None:
        result = await tool.ainvoke(
            {
                "action": "add",
                "prompt": "temp task",
                "at": "2030-12-31T23:59:00",
                "expires_after": "2030-12-31T00:00:00",
            }
        )
        parsed = json.loads(result)
        assert parsed["status"] == "success"

    @pytest.mark.asyncio
    async def test_add_with_invalid_expires_after(self, tool) -> None:
        result = await tool.ainvoke(
            {
                "action": "add",
                "prompt": "test",
                "every_minutes": 10,
                "recurring_confirmed": True,
                "expires_after": "not-a-date",
            }
        )
        assert "Invalid expires_after format" in result

    @pytest.mark.asyncio
    async def test_add_zero_max_fires_means_unlimited(self, tool, manager: CronManager) -> None:
        result = await tool.ainvoke(
            {
                "action": "add",
                "prompt": "unlimited task",
                "every_minutes": 10,
                "recurring_confirmed": True,
                "max_fires": 0,
            }
        )
        parsed = json.loads(result)
        assert parsed["status"] == "success"
        assert "max_fires" not in parsed

        job = await manager.get_job(parsed["job_id"], USER_ID)
        assert job is not None
        assert job.max_fires is None


# ---------------------------------------------------------------------------
# max_fires / expires_after in update
# ---------------------------------------------------------------------------


class TestUpdateWithLimits:
    @pytest.mark.asyncio
    async def test_update_max_fires(self, tool, manager: CronManager) -> None:
        job = await manager.create_job(
            user_id=USER_ID,
            name="test",
            job_type=JobType.AGENT,
            schedule=Schedule(kind=ScheduleKind.INTERVAL, interval_ms=300_000),
            prompt="check",
        )
        result = await tool.ainvoke(
            {
                "action": "update",
                "job_id": job.id,
                "max_fires": 50,
            }
        )
        parsed = json.loads(result)
        assert parsed["status"] == "success"
        assert parsed["max_fires"] == 50

    @pytest.mark.asyncio
    async def test_update_expires_after(self, tool, manager: CronManager) -> None:
        job = await manager.create_job(
            user_id=USER_ID,
            name="test",
            job_type=JobType.AGENT,
            schedule=Schedule(kind=ScheduleKind.INTERVAL, interval_ms=300_000),
            prompt="check",
        )
        result = await tool.ainvoke(
            {
                "action": "update",
                "job_id": job.id,
                "expires_after": "2w",
            }
        )
        parsed = json.loads(result)
        assert parsed["status"] == "success"
        assert "expires_at" in parsed


# ---------------------------------------------------------------------------
# List with progress display
# ---------------------------------------------------------------------------


class TestListProgress:
    @pytest.mark.asyncio
    async def test_list_shows_fire_count_progress(self, tool, manager: CronManager) -> None:
        job = await manager.create_job(
            user_id=USER_ID,
            name="auction-monitor",
            job_type=JobType.AGENT,
            schedule=Schedule(kind=ScheduleKind.INTERVAL, interval_ms=300_000),
            prompt="check auction",
            max_fires=100,
        )
        job.fire_count = 42
        await manager._store.save_job(job)

        result = await tool.ainvoke({"action": "list"})
        assert "[42/100]" in result
        assert "auction-monitor" in result

    @pytest.mark.asyncio
    async def test_list_no_progress_without_max_fires(self, tool, manager: CronManager) -> None:
        await manager.create_job(
            user_id=USER_ID,
            name="unlimited-job",
            job_type=JobType.AGENT,
            schedule=Schedule(kind=ScheduleKind.INTERVAL, interval_ms=300_000),
            prompt="check",
        )
        result = await tool.ainvoke({"action": "list"})
        assert "[" not in result or "unlimited-job" in result
        assert "/]" not in result

    @pytest.mark.asyncio
    async def test_list_paused_job_icon(self, tool, manager: CronManager) -> None:
        job = await manager.create_job(
            user_id=USER_ID,
            name="paused-task",
            job_type=JobType.AGENT,
            schedule=Schedule(kind=ScheduleKind.INTERVAL, interval_ms=300_000),
            prompt="check",
        )
        await manager.pause_job(job.id, USER_ID)

        result = await tool.ainvoke({"action": "list"})
        assert "||" in result
        assert "paused" in result


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_pause_resume_round_trip_preserves_history(self, tool, manager: CronManager) -> None:
        """Pause+resume preserves fire_count and configuration."""
        job = await manager.create_job(
            user_id=USER_ID,
            name="round-trip",
            job_type=JobType.AGENT,
            schedule=Schedule(kind=ScheduleKind.INTERVAL, interval_ms=300_000),
            prompt="monitor",
            max_fires=50,
        )
        job.fire_count = 10
        await manager._store.save_job(job)

        await tool.ainvoke({"action": "pause", "job_id": job.id})
        result = await tool.ainvoke({"action": "resume", "job_id": job.id})
        parsed = json.loads(result)
        assert parsed["status"] == "success"

        updated = await manager.get_job(job.id, USER_ID)
        assert updated is not None
        assert updated.fire_count == 10
        assert updated.max_fires == 50
        assert updated.status == JobStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_add_with_both_max_fires_and_expires_after(self, tool, manager: CronManager) -> None:
        result = await tool.ainvoke(
            {
                "action": "add",
                "prompt": "combo task",
                "every_minutes": 15,
                "recurring_confirmed": True,
                "max_fires": 200,
                "expires_after": "1m",
            }
        )
        parsed = json.loads(result)
        assert parsed["status"] == "success"
        assert parsed["max_fires"] == 200
        assert "expires_at" in parsed


# ---------------------------------------------------------------------------
# Cron execution guard (ContextVar)
# ---------------------------------------------------------------------------


class TestCronExecutionGuard:
    @pytest.mark.asyncio
    async def test_add_blocked_during_cron_execution(self, tool) -> None:
        token = enter_cron_execution_context()
        try:
            result = await tool.ainvoke(
                {
                    "action": "add",
                    "prompt": "should be blocked",
                    "every_minutes": 10,
                    "recurring_confirmed": True,
                }
            )
            assert "cannot create or modify" in result
            assert "infinite task chains" in result
        finally:
            exit_cron_execution_context(token)

    @pytest.mark.asyncio
    async def test_update_blocked_during_cron_execution(self, tool) -> None:
        token = enter_cron_execution_context()
        try:
            result = await tool.ainvoke(
                {
                    "action": "update",
                    "job_id": "any-id",
                    "prompt": "blocked",
                }
            )
            assert "cannot create or modify" in result
        finally:
            exit_cron_execution_context(token)

    @pytest.mark.asyncio
    async def test_list_allowed_during_cron_execution(self, tool) -> None:
        token = enter_cron_execution_context()
        try:
            result = await tool.ainvoke({"action": "list"})
            assert "no" in result.lower() or "task" in result.lower()
        finally:
            exit_cron_execution_context(token)


# ---------------------------------------------------------------------------
# Unknown action
# ---------------------------------------------------------------------------


class TestUnknownAction:
    @pytest.mark.asyncio
    async def test_unknown_action_rejected_by_pydantic(self, tool) -> None:
        """Invalid action values are rejected by Pydantic's Literal validation."""
        with pytest.raises(Exception):
            await tool.ainvoke({"action": "delete"})


# ---------------------------------------------------------------------------
# Schedule builder edge cases
# ---------------------------------------------------------------------------


class TestScheduleBuilder:
    @pytest.mark.asyncio
    async def test_add_no_schedule_param(self, tool) -> None:
        result = await tool.ainvoke({"action": "add", "prompt": "test"})
        assert "Provide one of" in result

    @pytest.mark.asyncio
    async def test_add_multiple_schedule_params(self, tool) -> None:
        result = await tool.ainvoke(
            {
                "action": "add",
                "prompt": "test",
                "cron_expr": "0 9 * * *",
                "every_minutes": 30,
                "recurring_confirmed": True,
            }
        )
        assert "only ONE" in result

    @pytest.mark.asyncio
    async def test_add_interval_too_small(self, tool) -> None:
        result = await tool.ainvoke(
            {
                "action": "add",
                "prompt": "test",
                "every_minutes": 2,
                "recurring_confirmed": True,
            }
        )
        assert "every_minutes must be >= 5" in result

    @pytest.mark.asyncio
    async def test_add_with_cron_expr(self, tool) -> None:
        result = await tool.ainvoke(
            {
                "action": "add",
                "prompt": "daily check",
                "cron_expr": "0 9 * * *",
                "recurring_confirmed": True,
            }
        )
        parsed = json.loads(result)
        assert parsed["status"] == "success"

    @pytest.mark.asyncio
    async def test_add_with_at_one_shot(self, tool) -> None:
        result = await tool.ainvoke(
            {
                "action": "add",
                "prompt": "remind me",
                "at": "2030-12-31T23:59:00",
            }
        )
        parsed = json.loads(result)
        assert parsed["status"] == "success"

    @pytest.mark.asyncio
    async def test_add_recurring_without_confirmation(self, tool) -> None:
        result = await tool.ainvoke(
            {
                "action": "add",
                "prompt": "test",
                "every_minutes": 10,
            }
        )
        assert "recurring_confirmed=true" in result


# ---------------------------------------------------------------------------
# Delivery resolution
# ---------------------------------------------------------------------------


class TestDeliveryResolution:
    @pytest.mark.asyncio
    async def test_add_with_feishu_webhook(self, tool) -> None:
        result = await tool.ainvoke(
            {
                "action": "add",
                "prompt": "monitor",
                "every_minutes": 60,
                "recurring_confirmed": True,
                "webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/xxx",
            }
        )
        parsed = json.loads(result)
        assert parsed["status"] == "success"

    @pytest.mark.asyncio
    async def test_add_with_generic_webhook(self, tool) -> None:
        result = await tool.ainvoke(
            {
                "action": "add",
                "prompt": "monitor",
                "every_minutes": 60,
                "recurring_confirmed": True,
                "webhook_url": "https://hooks.slack.com/services/xxx",
            }
        )
        parsed = json.loads(result)
        assert parsed["status"] == "success"


# ---------------------------------------------------------------------------
# Active hours
# ---------------------------------------------------------------------------


class TestActiveHours:
    @pytest.mark.asyncio
    async def test_add_with_active_hours(self, tool) -> None:
        result = await tool.ainvoke(
            {
                "action": "add",
                "prompt": "business hours only",
                "every_minutes": 30,
                "recurring_confirmed": True,
                "active_start": "09:00",
                "active_end": "18:00",
                "active_tz": "Asia/Shanghai",
            }
        )
        parsed = json.loads(result)
        assert parsed["status"] == "success"


# ---------------------------------------------------------------------------
# Add: prompt/command validation
# ---------------------------------------------------------------------------


class TestAddValidation:
    @pytest.mark.asyncio
    async def test_add_both_prompt_and_command(self, tool) -> None:
        result = await tool.ainvoke(
            {
                "action": "add",
                "prompt": "agent task",
                "command": "ls -la",
                "every_minutes": 10,
                "recurring_confirmed": True,
            }
        )
        assert "not both" in result

    @pytest.mark.asyncio
    async def test_add_neither_prompt_nor_command(self, tool) -> None:
        result = await tool.ainvoke(
            {
                "action": "add",
                "every_minutes": 10,
                "recurring_confirmed": True,
            }
        )
        assert "required" in result

    @pytest.mark.asyncio
    async def test_add_shell_command(self, tool) -> None:
        result = await tool.ainvoke(
            {
                "action": "add",
                "command": "echo hello",
                "every_minutes": 10,
                "recurring_confirmed": True,
            }
        )
        parsed = json.loads(result)
        assert parsed["status"] == "success"
        assert parsed["job_type"] == "Shell"


# ---------------------------------------------------------------------------
# Remove and Run edge cases
# ---------------------------------------------------------------------------


class TestRemoveRun:
    @pytest.mark.asyncio
    async def test_remove_missing_job_id(self, tool) -> None:
        result = await tool.ainvoke({"action": "remove"})
        assert "job_id required" in result

    @pytest.mark.asyncio
    async def test_remove_nonexistent_job(self, tool) -> None:
        result = await tool.ainvoke({"action": "remove", "job_id": "nope"})
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_remove_existing_job(self, tool, manager: CronManager) -> None:
        job = await manager.create_job(
            user_id=USER_ID,
            name="to-delete",
            job_type=JobType.AGENT,
            schedule=Schedule(kind=ScheduleKind.INTERVAL, interval_ms=300_000),
            prompt="temp",
        )
        result = await tool.ainvoke({"action": "remove", "job_id": job.id})
        assert "deleted" in result

    @pytest.mark.asyncio
    async def test_run_missing_job_id(self, tool) -> None:
        result = await tool.ainvoke({"action": "run"})
        assert "job_id required" in result

    @pytest.mark.asyncio
    async def test_run_nonexistent_job(self, tool) -> None:
        result = await tool.ainvoke({"action": "run", "job_id": "nope"})
        assert "not found" in result or "not active" in result


# ---------------------------------------------------------------------------
# Update edge cases
# ---------------------------------------------------------------------------


class TestUpdateEdgeCases:
    @pytest.mark.asyncio
    async def test_update_missing_job_id(self, tool) -> None:
        result = await tool.ainvoke({"action": "update"})
        assert "job_id required" in result

    @pytest.mark.asyncio
    async def test_update_nonexistent_job(self, tool) -> None:
        result = await tool.ainvoke({"action": "update", "job_id": "nope"})
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_update_invalid_expires_after(self, tool, manager: CronManager) -> None:
        job = await manager.create_job(
            user_id=USER_ID,
            name="test",
            job_type=JobType.AGENT,
            schedule=Schedule(kind=ScheduleKind.INTERVAL, interval_ms=300_000),
            prompt="check",
        )
        result = await tool.ainvoke(
            {
                "action": "update",
                "job_id": job.id,
                "expires_after": "not-a-date",
            }
        )
        assert "Invalid expires_after format" in result

    @pytest.mark.asyncio
    async def test_update_with_schedule_change(self, tool, manager: CronManager) -> None:
        job = await manager.create_job(
            user_id=USER_ID,
            name="test",
            job_type=JobType.AGENT,
            schedule=Schedule(kind=ScheduleKind.INTERVAL, interval_ms=300_000),
            prompt="check",
        )
        result = await tool.ainvoke(
            {
                "action": "update",
                "job_id": job.id,
                "cron_expr": "0 10 * * *",
            }
        )
        parsed = json.loads(result)
        assert parsed["status"] == "success"

    @pytest.mark.asyncio
    async def test_update_schedule_build_error(self, tool, manager: CronManager) -> None:
        job = await manager.create_job(
            user_id=USER_ID,
            name="test",
            job_type=JobType.AGENT,
            schedule=Schedule(kind=ScheduleKind.INTERVAL, interval_ms=300_000),
            prompt="check",
        )
        result = await tool.ainvoke(
            {
                "action": "update",
                "job_id": job.id,
                "cron_expr": "0 9 * * *",
                "every_minutes": 10,
            }
        )
        assert "only ONE" in result

    @pytest.mark.asyncio
    async def test_update_with_max_fires_shows_fire_count(self, tool, manager: CronManager) -> None:
        job = await manager.create_job(
            user_id=USER_ID,
            name="test",
            job_type=JobType.AGENT,
            schedule=Schedule(kind=ScheduleKind.INTERVAL, interval_ms=300_000),
            prompt="check",
        )
        result = await tool.ainvoke(
            {
                "action": "update",
                "job_id": job.id,
                "max_fires": 50,
            }
        )
        parsed = json.loads(result)
        assert parsed["max_fires"] == 50
        assert "fire_count" in parsed

    @pytest.mark.asyncio
    async def test_update_with_expires_at_in_response(self, tool, manager: CronManager) -> None:
        job = await manager.create_job(
            user_id=USER_ID,
            name="test",
            job_type=JobType.AGENT,
            schedule=Schedule(kind=ScheduleKind.INTERVAL, interval_ms=300_000),
            prompt="check",
        )
        result = await tool.ainvoke(
            {
                "action": "update",
                "job_id": job.id,
                "expires_after": "3d",
            }
        )
        parsed = json.loads(result)
        assert "expires_at" in parsed


# ---------------------------------------------------------------------------
# List edge cases
# ---------------------------------------------------------------------------


class TestListEdgeCases:
    @pytest.mark.asyncio
    async def test_list_empty(self, tool) -> None:
        result = await tool.ainvoke({"action": "list"})
        assert "No scheduled tasks" in result

    @pytest.mark.asyncio
    async def test_list_shell_job_type_tag(self, tool, manager: CronManager) -> None:
        await manager.create_job(
            user_id=USER_ID,
            name="backup",
            job_type=JobType.SHELL,
            schedule=Schedule(kind=ScheduleKind.INTERVAL, interval_ms=300_000),
            command="tar czf /tmp/backup.tar.gz /data",
        )
        result = await tool.ainvoke({"action": "list"})
        assert "[shell]" in result

    @pytest.mark.asyncio
    async def test_list_with_name_filter(self, tool, manager: CronManager) -> None:
        await manager.create_job(
            user_id=USER_ID,
            name="daily-backup",
            job_type=JobType.AGENT,
            schedule=Schedule(kind=ScheduleKind.INTERVAL, interval_ms=300_000),
            prompt="backup",
        )
        await manager.create_job(
            user_id=USER_ID,
            name="stock-monitor",
            job_type=JobType.AGENT,
            schedule=Schedule(kind=ScheduleKind.INTERVAL, interval_ms=300_000),
            prompt="monitor",
        )
        result = await tool.ainvoke({"action": "list", "name_filter": "backup"})
        assert "backup" in result

    @pytest.mark.asyncio
    async def test_list_shows_model_tag(self, tool, manager: CronManager) -> None:
        await manager.create_job(
            user_id=USER_ID,
            name="model-job",
            job_type=JobType.AGENT,
            schedule=Schedule(kind=ScheduleKind.INTERVAL, interval_ms=300_000),
            prompt="check",
            model="openai/gpt-4o-mini",
        )
        result = await tool.ainvoke({"action": "list"})
        assert "gpt-4o-mini" in result

    @pytest.mark.asyncio
    async def test_list_multiple_jobs_count(self, tool, manager: CronManager) -> None:
        for i in range(3):
            await manager.create_job(
                user_id=USER_ID,
                name=f"job-{i}",
                job_type=JobType.AGENT,
                schedule=Schedule(kind=ScheduleKind.INTERVAL, interval_ms=300_000),
                prompt=f"task {i}",
            )
        result = await tool.ainvoke({"action": "list"})
        assert "3 task(s)" in result


# ---------------------------------------------------------------------------
# Model fallback (current_model)
# ---------------------------------------------------------------------------


class TestModelFallback:
    @pytest.mark.asyncio
    async def test_add_uses_current_model_when_model_empty(self, manager: CronManager) -> None:
        tools = create_cron_tools(manager, USER_ID, current_model="openai/gpt-4o")
        t = tools[0]
        result = await t.ainvoke(
            {
                "action": "add",
                "prompt": "check",
                "every_minutes": 10,
                "recurring_confirmed": True,
            }
        )
        parsed = json.loads(result)
        assert parsed["status"] == "success"
        assert parsed["model"] == "openai/gpt-4o"

    @pytest.mark.asyncio
    async def test_add_explicit_model_overrides_current(self, manager: CronManager) -> None:
        tools = create_cron_tools(manager, USER_ID, current_model="openai/gpt-4o")
        t = tools[0]
        result = await t.ainvoke(
            {
                "action": "add",
                "prompt": "check",
                "every_minutes": 10,
                "recurring_confirmed": True,
                "model": "anthropic/claude-sonnet-4-20250514",
            }
        )
        parsed = json.loads(result)
        assert parsed["model"] == "anthropic/claude-sonnet-4-20250514"


# ---------------------------------------------------------------------------
# chat_id passing
# ---------------------------------------------------------------------------


class TestChatIdPassing:
    @pytest.mark.asyncio
    async def test_add_with_chat_id(self, manager: CronManager) -> None:
        tools = create_cron_tools(manager, USER_ID, current_model="test", chat_id="chat-123")
        t = tools[0]
        result = await t.ainvoke(
            {
                "action": "add",
                "prompt": "check",
                "every_minutes": 10,
                "recurring_confirmed": True,
            }
        )
        parsed = json.loads(result)
        job = await manager.get_job(parsed["job_id"], USER_ID)
        assert job is not None
        assert job.chat_id == "chat-123"


# ---------------------------------------------------------------------------
# Failure webhook
# ---------------------------------------------------------------------------


class TestFailureWebhook:
    @pytest.mark.asyncio
    async def test_add_with_failure_webhook(self, tool, manager: CronManager) -> None:
        result = await tool.ainvoke(
            {
                "action": "add",
                "prompt": "monitor",
                "every_minutes": 30,
                "recurring_confirmed": True,
                "failure_webhook_url": "https://hooks.slack.com/alert",
            }
        )
        parsed = json.loads(result)
        assert parsed["status"] == "success"
        job = await manager.get_job(parsed["job_id"], USER_ID)
        assert job is not None
        assert job.failure_delivery is not None
        assert job.failure_delivery.channel == "webhook"


# ---------------------------------------------------------------------------
# Lark Suite delivery
# ---------------------------------------------------------------------------


class TestLarkSuiteDelivery:
    @pytest.mark.asyncio
    async def test_add_with_larksuite_webhook(self, tool) -> None:
        result = await tool.ainvoke(
            {
                "action": "add",
                "prompt": "monitor",
                "every_minutes": 60,
                "recurring_confirmed": True,
                "webhook_url": "https://open.larksuite.com/open-apis/bot/v2/hook/xxx",
            }
        )
        parsed = json.loads(result)
        assert parsed["status"] == "success"


# ---------------------------------------------------------------------------
# Active hours partial input
# ---------------------------------------------------------------------------


class TestActiveHoursPartial:
    @pytest.mark.asyncio
    async def test_active_start_only_ignored(self, tool) -> None:
        result = await tool.ainvoke(
            {
                "action": "add",
                "prompt": "test",
                "every_minutes": 10,
                "recurring_confirmed": True,
                "active_start": "09:00",
            }
        )
        parsed = json.loads(result)
        assert parsed["status"] == "success"

    @pytest.mark.asyncio
    async def test_active_end_only_ignored(self, tool) -> None:
        result = await tool.ainvoke(
            {
                "action": "add",
                "prompt": "test",
                "every_minutes": 10,
                "recurring_confirmed": True,
                "active_end": "18:00",
            }
        )
        parsed = json.loads(result)
        assert parsed["status"] == "success"


# ---------------------------------------------------------------------------
# Auto-generated name
# ---------------------------------------------------------------------------


class TestAutoName:
    @pytest.mark.asyncio
    async def test_add_agent_auto_name(self, tool, manager: CronManager) -> None:
        result = await tool.ainvoke(
            {
                "action": "add",
                "prompt": "check the weather forecast in Tokyo",
                "every_minutes": 60,
                "recurring_confirmed": True,
            }
        )
        parsed = json.loads(result)
        assert parsed["status"] == "success"
        assert parsed["name"]
        assert len(parsed["name"]) > 0

    @pytest.mark.asyncio
    async def test_add_shell_auto_name(self, tool, manager: CronManager) -> None:
        result = await tool.ainvoke(
            {
                "action": "add",
                "command": "df -h",
                "every_minutes": 30,
                "recurring_confirmed": True,
            }
        )
        parsed = json.loads(result)
        assert parsed["status"] == "success"
        assert parsed["name"]

    @pytest.mark.asyncio
    async def test_add_with_custom_name(self, tool, manager: CronManager) -> None:
        result = await tool.ainvoke(
            {
                "action": "add",
                "prompt": "check",
                "every_minutes": 10,
                "recurring_confirmed": True,
                "name": "my-custom-task",
            }
        )
        parsed = json.loads(result)
        assert parsed["name"] == "my-custom-task"

    @pytest.mark.asyncio
    async def test_add_shell_with_custom_name(self, tool, manager: CronManager) -> None:
        result = await tool.ainvoke(
            {
                "action": "add",
                "command": "ls",
                "every_minutes": 10,
                "recurring_confirmed": True,
                "name": "shell-custom",
            }
        )
        parsed = json.loads(result)
        assert parsed["name"] == "shell-custom"


# ---------------------------------------------------------------------------
# ContextVar guard — non-mutating actions allowed in cron context
# ---------------------------------------------------------------------------


class TestCronGuardNonMutating:
    @pytest.mark.asyncio
    async def test_pause_allowed_during_cron_execution(self, tool, manager: CronManager) -> None:
        job = await manager.create_job(
            user_id=USER_ID,
            name="test",
            job_type=JobType.AGENT,
            schedule=Schedule(kind=ScheduleKind.INTERVAL, interval_ms=300_000),
            prompt="check",
        )
        token = enter_cron_execution_context()
        try:
            result = await tool.ainvoke({"action": "pause", "job_id": job.id})
            parsed = json.loads(result)
            assert parsed["status"] == "success"
        finally:
            exit_cron_execution_context(token)

    @pytest.mark.asyncio
    async def test_resume_allowed_during_cron_execution(self, tool, manager: CronManager) -> None:
        job = await manager.create_job(
            user_id=USER_ID,
            name="test",
            job_type=JobType.AGENT,
            schedule=Schedule(kind=ScheduleKind.INTERVAL, interval_ms=300_000),
            prompt="check",
        )
        await manager.pause_job(job.id, USER_ID)
        token = enter_cron_execution_context()
        try:
            result = await tool.ainvoke({"action": "resume", "job_id": job.id})
            parsed = json.loads(result)
            assert parsed["status"] == "success"
        finally:
            exit_cron_execution_context(token)

    @pytest.mark.asyncio
    async def test_remove_allowed_during_cron_execution(self, tool, manager: CronManager) -> None:
        job = await manager.create_job(
            user_id=USER_ID,
            name="test",
            job_type=JobType.AGENT,
            schedule=Schedule(kind=ScheduleKind.INTERVAL, interval_ms=300_000),
            prompt="check",
        )
        token = enter_cron_execution_context()
        try:
            result = await tool.ainvoke({"action": "remove", "job_id": job.id})
            assert "deleted" in result
        finally:
            exit_cron_execution_context(token)


# ---------------------------------------------------------------------------
# _parse_expires_after boundary values
# ---------------------------------------------------------------------------


class TestParseExpiresAfterBoundary:
    def test_one_day(self) -> None:
        result = _parse_expires_after("1d")
        assert result is not None
        delta = result - datetime.now(UTC)
        assert 0 <= delta.days <= 1

    def test_one_week(self) -> None:
        result = _parse_expires_after("1w")
        assert result is not None
        delta = result - datetime.now(UTC)
        assert 6 <= delta.days <= 7

    def test_one_month(self) -> None:
        result = _parse_expires_after("1m")
        assert result is not None
        delta = result - datetime.now(UTC)
        assert 29 <= delta.days <= 30

    def test_large_value(self) -> None:
        result = _parse_expires_after("365d")
        assert result is not None
        delta = result - datetime.now(UTC)
        assert 364 <= delta.days <= 365


# ---------------------------------------------------------------------------
# Update: prompt/name/command changes
# ---------------------------------------------------------------------------


class TestUpdateFieldChanges:
    @pytest.mark.asyncio
    async def test_update_prompt(self, tool, manager: CronManager) -> None:
        job = await manager.create_job(
            user_id=USER_ID,
            name="test",
            job_type=JobType.AGENT,
            schedule=Schedule(kind=ScheduleKind.INTERVAL, interval_ms=300_000),
            prompt="old prompt",
        )
        result = await tool.ainvoke(
            {
                "action": "update",
                "job_id": job.id,
                "prompt": "new prompt",
            }
        )
        parsed = json.loads(result)
        assert parsed["status"] == "success"

        updated = await manager.get_job(job.id, USER_ID)
        assert updated is not None
        assert updated.prompt == "new prompt"

    @pytest.mark.asyncio
    async def test_update_name(self, tool, manager: CronManager) -> None:
        job = await manager.create_job(
            user_id=USER_ID,
            name="old-name",
            job_type=JobType.AGENT,
            schedule=Schedule(kind=ScheduleKind.INTERVAL, interval_ms=300_000),
            prompt="check",
        )
        result = await tool.ainvoke(
            {
                "action": "update",
                "job_id": job.id,
                "name": "new-name",
            }
        )
        parsed = json.loads(result)
        assert parsed["name"] == "new-name"

    @pytest.mark.asyncio
    async def test_update_model(self, tool, manager: CronManager) -> None:
        job = await manager.create_job(
            user_id=USER_ID,
            name="test",
            job_type=JobType.AGENT,
            schedule=Schedule(kind=ScheduleKind.INTERVAL, interval_ms=300_000),
            prompt="check",
            model="old-model",
        )
        result = await tool.ainvoke(
            {
                "action": "update",
                "job_id": job.id,
                "model": "new-model",
            }
        )
        parsed = json.loads(result)
        assert parsed["model"] == "new-model"


# ---------------------------------------------------------------------------
# Add response format validation
# ---------------------------------------------------------------------------


class TestAddResponseFormat:
    @pytest.mark.asyncio
    async def test_add_response_contains_all_fields(self, tool) -> None:
        result = await tool.ainvoke(
            {
                "action": "add",
                "prompt": "check weather",
                "cron_expr": "0 9 * * *",
                "recurring_confirmed": True,
            }
        )
        parsed = json.loads(result)
        assert "status" in parsed
        assert "action" in parsed
        assert "job_id" in parsed
        assert "name" in parsed
        assert "job_type" in parsed
        assert "schedule" in parsed
        assert "next_run" in parsed
        assert parsed["action"] == "add"
        assert parsed["job_type"] == "Agent"

    @pytest.mark.asyncio
    async def test_add_response_with_tz(self, tool) -> None:
        result = await tool.ainvoke(
            {
                "action": "add",
                "prompt": "check",
                "cron_expr": "0 9 * * *",
                "recurring_confirmed": True,
                "tz": "Asia/Shanghai",
            }
        )
        parsed = json.loads(result)
        assert parsed["status"] == "success"


class TestAgentIdInheritance:
    """Verify agent_id is passed through create_cron_tools to created jobs."""

    @pytest.mark.asyncio
    async def test_add_inherits_agent_id(self, manager: CronManager, store: InMemoryCronStore) -> None:
        tools = create_cron_tools(manager, USER_ID, current_model="m", agent_id="my-agent")
        tool = tools[0]
        result = await tool.ainvoke(
            {
                "action": "add",
                "prompt": "analyse logs",
                "at": "2099-01-01T00:00:00",
            }
        )
        parsed = json.loads(result)
        assert parsed["status"] == "success"
        job = await store.get_job(parsed["job_id"])
        assert job is not None
        assert job.agent_id == "my-agent"

    @pytest.mark.asyncio
    async def test_add_without_agent_id(self, manager: CronManager, store: InMemoryCronStore) -> None:
        tools = create_cron_tools(manager, USER_ID, current_model="m")
        tool = tools[0]
        result = await tool.ainvoke(
            {
                "action": "add",
                "prompt": "simple task",
                "at": "2099-06-01T00:00:00",
            }
        )
        parsed = json.loads(result)
        assert parsed["status"] == "success"
        job = await store.get_job(parsed["job_id"])
        assert job is not None
        assert job.agent_id is None


# ---------------------------------------------------------------------------
# _parse_context_from tests
# ---------------------------------------------------------------------------


class TestParseContextFrom:
    """Tests for the _parse_context_from helper."""

    def test_empty_string(self) -> None:
        assert _parse_context_from("") == ()

    def test_whitespace_only(self) -> None:
        assert _parse_context_from("   ") == ()

    def test_single_id(self) -> None:
        assert _parse_context_from("abc123") == ("abc123",)

    def test_multiple_ids(self) -> None:
        assert _parse_context_from("abc,def,ghi") == ("abc", "def", "ghi")

    def test_whitespace_stripped(self) -> None:
        assert _parse_context_from(" abc , def , ghi ") == ("abc", "def", "ghi")

    def test_duplicates_removed(self) -> None:
        assert _parse_context_from("abc,def,abc,ghi,def") == ("abc", "def", "ghi")

    def test_empty_segments_filtered(self) -> None:
        assert _parse_context_from("abc,,def,,,ghi") == ("abc", "def", "ghi")


# ---------------------------------------------------------------------------
# context_from in cron_manage tool
# ---------------------------------------------------------------------------


class TestCronManageContextFrom:
    """Tests for context_from parameter in cron_manage add/update/list."""

    @pytest.mark.asyncio
    async def test_add_with_context_from(
        self, manager: CronManager, store: InMemoryCronStore
    ) -> None:
        ref_job = await manager.create_job(
            user_id=USER_ID,
            name="Data Collector",
            job_type=JobType.AGENT,
            schedule=Schedule(kind=ScheduleKind.ONCE, run_at=datetime(2099, 1, 1, tzinfo=UTC)),
            prompt="collect data",
        )
        tools = create_cron_tools(manager, USER_ID, current_model="m")
        tool = tools[0]
        result = await tool.ainvoke(
            {
                "action": "add",
                "prompt": "analyze data",
                "at": "2099-06-01T00:00:00",
                "context_from": ref_job.id,
            }
        )
        parsed = json.loads(result)
        assert parsed["status"] == "success"
        assert parsed.get("context_from") == [ref_job.id]

        created = await store.get_job(parsed["job_id"])
        assert created is not None
        assert created.context_from == (ref_job.id,)

    @pytest.mark.asyncio
    async def test_add_with_invalid_context_from(self, manager: CronManager) -> None:
        tools = create_cron_tools(manager, USER_ID, current_model="m")
        tool = tools[0]
        result = await tool.ainvoke(
            {
                "action": "add",
                "prompt": "analyze",
                "at": "2099-06-01T00:00:00",
                "context_from": "nonexistent-job",
            }
        )
        assert "non-existent" in result

    @pytest.mark.asyncio
    async def test_list_shows_context_from(
        self, manager: CronManager, store: InMemoryCronStore
    ) -> None:
        ref_job = await manager.create_job(
            user_id=USER_ID,
            name="Source",
            job_type=JobType.AGENT,
            schedule=Schedule(kind=ScheduleKind.ONCE, run_at=datetime(2099, 1, 1, tzinfo=UTC)),
            prompt="collect",
        )
        await manager.create_job(
            user_id=USER_ID,
            name="Consumer",
            job_type=JobType.AGENT,
            schedule=Schedule(kind=ScheduleKind.ONCE, run_at=datetime(2099, 1, 1, tzinfo=UTC)),
            prompt="analyze",
            context_from=(ref_job.id,),
        )
        tools = create_cron_tools(manager, USER_ID, current_model="m")
        tool = tools[0]
        result = await tool.ainvoke({"action": "list"})
        assert ref_job.id in result
