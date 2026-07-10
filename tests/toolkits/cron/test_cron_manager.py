"""Unit tests for CronManager — CRUD, patch logic, validation, and queries."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.toolkits.cron.manager import CronManager
from myrm_agent_harness.toolkits.cron.types import (
    ActiveHours,
    CronJob,
    CronJobPatch,
    DeliveryConfig,
    FailureAlertConfig,
    JobStatus,
    JobType,
    Schedule,
    ScheduleKind,
    SessionTarget,
)


def _make_schedule(kind: ScheduleKind = ScheduleKind.CRON, expr: str = "0 * * * *") -> Schedule:
    return Schedule(kind=kind, expr=expr)


def _make_job(**kwargs: object) -> CronJob:
    defaults: dict[str, object] = {
        "id": "job-1",
        "user_id": "user-1",
        "name": "Test Job",
        "job_type": JobType.AGENT,
        "schedule": _make_schedule(),
        "status": JobStatus.ACTIVE,
        "prompt": "test prompt",
    }
    defaults.update(kwargs)
    return CronJob(**defaults)  # type: ignore[arg-type]


def _make_manager(*, shell_enabled: bool = True) -> CronManager:
    store = AsyncMock()
    store.save_job = AsyncMock(side_effect=lambda j: j)
    store.get_job = AsyncMock()
    store.get_monitor_state = AsyncMock(return_value=None)
    store.delete_job_cascade = AsyncMock(return_value=True)
    store.save_monitor_state = AsyncMock()
    store.delete_monitor_state = AsyncMock()
    store.list_jobs = AsyncMock(return_value=[])
    store.count_jobs = AsyncMock(return_value=0)
    store.list_runs = AsyncMock(return_value=[])
    store.count_runs = AsyncMock(return_value=0)
    store.batch_get_monitor_states = AsyncMock(return_value={})
    scheduler = MagicMock()
    scheduler.notify_change = MagicMock()
    return CronManager(store=store, scheduler=scheduler, shell_enabled=shell_enabled)


# ---------------------------------------------------------------------------
# create_job — new fields
# ---------------------------------------------------------------------------


class TestCreateJobNewFields:
    @pytest.mark.asyncio
    async def test_defaults(self):
        mgr = _make_manager()
        job = await mgr.create_job("user-1", "Test", JobType.AGENT, _make_schedule(), prompt="hello")
        assert job.cooldown_seconds == 0
        assert job.max_fires is None
        assert job.expires_at is None
        assert job.session_target == SessionTarget.ISOLATED
        assert job.run_retention_days == 30
        assert job.failure_alert is None

    @pytest.mark.asyncio
    async def test_custom_values(self):
        dt = datetime(2026, 12, 31, tzinfo=UTC)
        fa = FailureAlertConfig(after=5, cooldown_seconds=600)
        mgr = _make_manager()
        job = await mgr.create_job(
            "user-1",
            "Test",
            JobType.AGENT,
            _make_schedule(),
            prompt="hello",
            cooldown_seconds=60,
            max_fires=100,
            expires_at=dt,
            session_target=SessionTarget.MAIN,
            run_retention_days=90,
            failure_alert=fa,
        )
        assert job.cooldown_seconds == 60
        assert job.max_fires == 100
        assert job.expires_at == dt
        assert job.session_target == SessionTarget.MAIN
        assert job.run_retention_days == 90
        assert job.failure_alert == fa


# ---------------------------------------------------------------------------
# update_job — patch application for all clear_xxx patterns
# ---------------------------------------------------------------------------


class TestUpdateJobPatch:
    @pytest.fixture()
    def mgr(self) -> CronManager:
        return _make_manager()

    async def _do_update(self, mgr: CronManager, job: CronJob, patch: CronJobPatch) -> CronJob:
        mgr._store.get_job = AsyncMock(return_value=job)
        result = await mgr.update_job(job.id, job.user_id, patch)
        assert result is not None
        return result

    # --- clear_max_fires ---

    @pytest.mark.asyncio
    async def test_clear_max_fires(self, mgr: CronManager):
        job = _make_job(max_fires=100)
        result = await self._do_update(mgr, job, CronJobPatch(clear_max_fires=True))
        assert result.max_fires is None

    @pytest.mark.asyncio
    async def test_set_max_fires(self, mgr: CronManager):
        job = _make_job(max_fires=None)
        result = await self._do_update(mgr, job, CronJobPatch(max_fires=50))
        assert result.max_fires == 50

    @pytest.mark.asyncio
    async def test_clear_max_fires_takes_precedence(self, mgr: CronManager):
        job = _make_job(max_fires=100)
        result = await self._do_update(mgr, job, CronJobPatch(clear_max_fires=True, max_fires=50))
        assert result.max_fires is None

    # --- clear_expires_at ---

    @pytest.mark.asyncio
    async def test_clear_expires_at(self, mgr: CronManager):
        dt = datetime(2026, 12, 31, tzinfo=UTC)
        job = _make_job(expires_at=dt)
        result = await self._do_update(mgr, job, CronJobPatch(clear_expires_at=True))
        assert result.expires_at is None

    @pytest.mark.asyncio
    async def test_set_expires_at(self, mgr: CronManager):
        dt = datetime(2027, 6, 15, tzinfo=UTC)
        job = _make_job(expires_at=None)
        result = await self._do_update(mgr, job, CronJobPatch(expires_at=dt))
        assert result.expires_at == dt

    # --- clear_failure_alert ---

    @pytest.mark.asyncio
    async def test_clear_failure_alert(self, mgr: CronManager):
        fa = FailureAlertConfig(after=5)
        job = _make_job(failure_alert=fa)
        result = await self._do_update(mgr, job, CronJobPatch(clear_failure_alert=True))
        assert result.failure_alert is False

    @pytest.mark.asyncio
    async def test_set_failure_alert(self, mgr: CronManager):
        fa = FailureAlertConfig(after=10, cooldown_seconds=1200)
        job = _make_job(failure_alert=None)
        result = await self._do_update(mgr, job, CronJobPatch(failure_alert=fa))
        assert result.failure_alert == fa

    # --- clear_failure_delivery ---

    @pytest.mark.asyncio
    async def test_clear_failure_delivery(self, mgr: CronManager):
        d = DeliveryConfig(channel="webhook", target="https://x.com")
        job = _make_job(failure_delivery=d)
        result = await self._do_update(mgr, job, CronJobPatch(clear_failure_delivery=True))
        assert result.failure_delivery is None

    @pytest.mark.asyncio
    async def test_set_failure_delivery(self, mgr: CronManager):
        d = DeliveryConfig(channel="webhook", target="https://y.com")
        job = _make_job(failure_delivery=None)
        result = await self._do_update(mgr, job, CronJobPatch(failure_delivery=d))
        assert result.failure_delivery == d

    # --- clear_active_hours ---

    @pytest.mark.asyncio
    async def test_clear_active_hours(self, mgr: CronManager):
        ah = ActiveHours(start="09:00", end="18:00")
        job = _make_job(active_hours=ah)
        result = await self._do_update(mgr, job, CronJobPatch(clear_active_hours=True))
        assert result.active_hours is None

    # --- cooldown_seconds ---

    @pytest.mark.asyncio
    async def test_set_cooldown(self, mgr: CronManager):
        job = _make_job(cooldown_seconds=0)
        result = await self._do_update(mgr, job, CronJobPatch(cooldown_seconds=120))
        assert result.cooldown_seconds == 120

    # --- session_target ---

    @pytest.mark.asyncio
    async def test_set_session_target(self, mgr: CronManager):
        job = _make_job(session_target=SessionTarget.ISOLATED)
        result = await self._do_update(mgr, job, CronJobPatch(session_target=SessionTarget.MAIN))
        assert result.session_target == SessionTarget.MAIN

    # --- chat_id ---

    @pytest.mark.asyncio
    async def test_set_chat_id(self, mgr: CronManager):
        job = _make_job(session_target=SessionTarget.MAIN, chat_id=None)
        result = await self._do_update(mgr, job, CronJobPatch(chat_id="chat-new"))
        assert result.chat_id == "chat-new"

    @pytest.mark.asyncio
    async def test_change_chat_id(self, mgr: CronManager):
        job = _make_job(session_target=SessionTarget.MAIN, chat_id="chat-old")
        result = await self._do_update(mgr, job, CronJobPatch(chat_id="chat-new"))
        assert result.chat_id == "chat-new"

    @pytest.mark.asyncio
    async def test_clear_chat_id(self, mgr: CronManager):
        job = _make_job(session_target=SessionTarget.ISOLATED, chat_id="chat-old")
        result = await self._do_update(mgr, job, CronJobPatch(clear_chat_id=True))
        assert result.chat_id is None

    @pytest.mark.asyncio
    async def test_empty_patch_preserves_chat_id(self, mgr: CronManager):
        job = _make_job(session_target=SessionTarget.MAIN, chat_id="chat-keep")
        result = await self._do_update(mgr, job, CronJobPatch())
        assert result.chat_id == "chat-keep"

    # --- run_retention_days ---

    @pytest.mark.asyncio
    async def test_set_run_retention_days(self, mgr: CronManager):
        job = _make_job(run_retention_days=30)
        result = await self._do_update(mgr, job, CronJobPatch(run_retention_days=90))
        assert result.run_retention_days == 90

    # --- delete_after_run ---

    @pytest.mark.asyncio
    async def test_set_delete_after_run(self, mgr: CronManager):
        job = _make_job(delete_after_run=False)
        result = await self._do_update(mgr, job, CronJobPatch(delete_after_run=True))
        assert result.delete_after_run is True

    # --- ownership check ---

    @pytest.mark.asyncio
    async def test_wrong_user_returns_none(self, mgr: CronManager):
        job = _make_job(user_id="user-1")
        mgr._store.get_job = AsyncMock(return_value=job)
        result = await mgr.update_job(job.id, "user-2", CronJobPatch(name="hack"))
        assert result is None

    @pytest.mark.asyncio
    async def test_missing_job_returns_none(self, mgr: CronManager):
        mgr._store.get_job = AsyncMock(return_value=None)
        result = await mgr.update_job("nonexistent", "user-1", CronJobPatch(name="x"))
        assert result is None

    # --- empty patch ---

    @pytest.mark.asyncio
    async def test_empty_patch_preserves_all(self, mgr: CronManager):
        dt = datetime(2026, 12, 31, tzinfo=UTC)
        fa = FailureAlertConfig(after=5)
        job = _make_job(
            cooldown_seconds=60,
            max_fires=100,
            expires_at=dt,
            session_target=SessionTarget.MAIN,
            failure_alert=fa,
            run_retention_days=90,
        )
        result = await self._do_update(mgr, job, CronJobPatch())
        assert result.cooldown_seconds == 60
        assert result.max_fires == 100
        assert result.expires_at == dt
        assert result.session_target == SessionTarget.MAIN
        assert result.failure_alert == fa
        assert result.run_retention_days == 90


# ---------------------------------------------------------------------------
# Query methods
# ---------------------------------------------------------------------------


class TestQueryMethods:
    @pytest.mark.asyncio
    async def test_list_jobs(self) -> None:
        mgr = _make_manager()
        jobs = [_make_job()]
        mgr._store.list_jobs = AsyncMock(return_value=jobs)
        result = await mgr.list_jobs("user-1", limit=10, offset=0)
        assert result == jobs
        mgr._store.list_jobs.assert_awaited_once_with(user_id="user-1", name_filter=None, limit=10, offset=0)

    @pytest.mark.asyncio
    async def test_count_jobs(self) -> None:
        mgr = _make_manager()
        mgr._store.count_jobs = AsyncMock(return_value=5)
        assert await mgr.count_jobs("user-1") == 5

    @pytest.mark.asyncio
    async def test_get_job_found(self) -> None:
        mgr = _make_manager()
        job = _make_job()
        mgr._store.get_job = AsyncMock(return_value=job)
        assert await mgr.get_job("job-1", "user-1") == job

    @pytest.mark.asyncio
    async def test_get_job_wrong_user(self) -> None:
        mgr = _make_manager()
        job = _make_job(user_id="user-1")
        mgr._store.get_job = AsyncMock(return_value=job)
        assert await mgr.get_job("job-1", "user-2") is None

    @pytest.mark.asyncio
    async def test_get_job_not_found(self) -> None:
        mgr = _make_manager()
        mgr._store.get_job = AsyncMock(return_value=None)
        assert await mgr.get_job("nonexistent", "user-1") is None

    @pytest.mark.asyncio
    async def test_list_runs_with_job_id_wrong_user(self) -> None:
        mgr = _make_manager()
        job = _make_job(user_id="user-1")
        mgr._store.get_job = AsyncMock(return_value=job)
        result = await mgr.list_runs("user-2", job_id="job-1")
        assert result == []
        mgr._store.list_runs.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_list_runs_without_job_id(self) -> None:
        mgr = _make_manager()
        await mgr.list_runs("user-1")
        mgr._store.list_runs.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_count_runs_with_job_id_wrong_user(self) -> None:
        mgr = _make_manager()
        job = _make_job(user_id="user-1")
        mgr._store.get_job = AsyncMock(return_value=job)
        result = await mgr.count_runs("user-2", job_id="job-1")
        assert result == 0
        mgr._store.count_runs.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_count_runs_without_job_id(self) -> None:
        mgr = _make_manager()
        mgr._store.count_runs = AsyncMock(return_value=3)
        result = await mgr.count_runs("user-1")
        assert result == 3

    @pytest.mark.asyncio
    async def test_get_monitor_state(self) -> None:
        mgr = _make_manager()
        await mgr.get_monitor_state("job-1")
        mgr._store.get_monitor_state.assert_awaited_once_with("job-1")

    @pytest.mark.asyncio
    async def test_batch_get_monitor_states(self) -> None:
        mgr = _make_manager()
        await mgr.batch_get_monitor_states(["job-1", "job-2"])
        mgr._store.batch_get_monitor_states.assert_awaited_once_with(["job-1", "job-2"])


# ---------------------------------------------------------------------------
# delete_job
# ---------------------------------------------------------------------------


class TestDeleteJob:
    @pytest.mark.asyncio
    async def test_delete_success(self) -> None:
        mgr = _make_manager()
        job = _make_job()
        mgr._store.get_job = AsyncMock(return_value=job)
        assert await mgr.delete_job("job-1", "user-1") is True
        mgr._store.delete_job_cascade.assert_awaited_once_with("job-1")
        mgr._scheduler.notify_change.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_wrong_user(self) -> None:
        mgr = _make_manager()
        job = _make_job(user_id="user-1")
        mgr._store.get_job = AsyncMock(return_value=job)
        assert await mgr.delete_job("job-1", "user-2") is False

    @pytest.mark.asyncio
    async def test_delete_not_found(self) -> None:
        mgr = _make_manager()
        mgr._store.get_job = AsyncMock(return_value=None)
        assert await mgr.delete_job("nonexistent", "user-1") is False


# ---------------------------------------------------------------------------
# reset_monitor_baseline
# ---------------------------------------------------------------------------


class TestResetMonitorBaseline:
    @pytest.mark.asyncio
    async def test_reset_success(self) -> None:
        from myrm_agent_harness.infra.incremental.types import MonitorState

        mgr = _make_manager()
        job = _make_job()
        state = MonitorState(job_id="job-1", monitor_type="text_diff", data={"some": "data"})
        mgr._store.get_job = AsyncMock(return_value=job)
        mgr._store.get_monitor_state = AsyncMock(return_value=state)
        assert await mgr.reset_monitor_baseline("job-1", "user-1") is True
        assert state.data == {}
        assert state.last_reset_reason == "manual"
        mgr._store.save_monitor_state.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_reset_no_state(self) -> None:
        mgr = _make_manager()
        job = _make_job()
        mgr._store.get_job = AsyncMock(return_value=job)
        mgr._store.get_monitor_state = AsyncMock(return_value=None)
        assert await mgr.reset_monitor_baseline("job-1", "user-1") is False

    @pytest.mark.asyncio
    async def test_reset_wrong_user(self) -> None:
        mgr = _make_manager()
        job = _make_job(user_id="user-1")
        mgr._store.get_job = AsyncMock(return_value=job)
        assert await mgr.reset_monitor_baseline("job-1", "user-2") is False


# ---------------------------------------------------------------------------
# pause / resume / trigger_now
# ---------------------------------------------------------------------------


class TestPauseResumeTrigger:
    @pytest.mark.asyncio
    async def test_pause_job(self) -> None:
        mgr = _make_manager()
        job = _make_job()
        mgr._store.get_job = AsyncMock(return_value=job)
        result = await mgr.pause_job("job-1", "user-1")
        assert result is not None
        assert result.status == JobStatus.PAUSED

    @pytest.mark.asyncio
    async def test_resume_job(self) -> None:
        mgr = _make_manager()
        job = _make_job(status=JobStatus.PAUSED, consecutive_failures=5)
        mgr._store.get_job = AsyncMock(return_value=job)
        result = await mgr.resume_job("job-1", "user-1")
        assert result is not None
        assert result.status == JobStatus.ACTIVE
        assert result.consecutive_failures == 0
        assert result.next_run_at is not None

    @pytest.mark.asyncio
    async def test_resume_wrong_user(self) -> None:
        mgr = _make_manager()
        job = _make_job(user_id="user-1")
        mgr._store.get_job = AsyncMock(return_value=job)
        assert await mgr.resume_job("job-1", "user-2") is None

    @pytest.mark.asyncio
    async def test_trigger_now(self) -> None:
        mgr = _make_manager()
        job = _make_job(status=JobStatus.ACTIVE)
        mgr._store.get_job = AsyncMock(return_value=job)
        assert await mgr.trigger_now("job-1", "user-1") is True
        mgr._store.save_job.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_trigger_now_paused_job(self) -> None:
        mgr = _make_manager()
        job = _make_job(status=JobStatus.PAUSED)
        mgr._store.get_job = AsyncMock(return_value=job)
        assert await mgr.trigger_now("job-1", "user-1") is False

    @pytest.mark.asyncio
    async def test_trigger_now_wrong_user(self) -> None:
        mgr = _make_manager()
        job = _make_job(user_id="user-1")
        mgr._store.get_job = AsyncMock(return_value=job)
        assert await mgr.trigger_now("job-1", "user-2") is False


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_agent_requires_prompt(self) -> None:
        mgr = _make_manager()
        with pytest.raises(ValueError, match="(?i)agent job requires a non-empty"):
            mgr._validate_create(JobType.AGENT, _make_schedule(), None, None)

    def test_shell_requires_command(self) -> None:
        mgr = _make_manager()
        with pytest.raises(ValueError, match="(?i)shell job requires a non-empty"):
            mgr._validate_create(JobType.SHELL, _make_schedule(), None, None)

    def test_shell_disabled(self) -> None:
        mgr = _make_manager(shell_enabled=False)
        with pytest.raises(ValueError, match="shell jobs are not enabled"):
            mgr._validate_create(JobType.SHELL, _make_schedule(), None, "echo hi")

    def test_invalid_cron_expr(self) -> None:
        mgr = _make_manager()
        bad_schedule = _make_schedule(expr="not-valid")
        with pytest.raises(ValueError, match="invalid cron expression"):
            mgr._validate_create(JobType.AGENT, bad_schedule, "prompt", None)

    def test_invalid_timezone(self) -> None:
        mgr = _make_manager()
        tz_schedule = Schedule(kind=ScheduleKind.CRON, expr="0 * * * *", tz="Fake/Zone")
        with pytest.raises(ValueError, match="unknown timezone"):
            mgr._validate_create(JobType.AGENT, tz_schedule, "prompt", None)


# ---------------------------------------------------------------------------
# update_job — monitor baseline auto-reset
# ---------------------------------------------------------------------------


class TestUpdateJobMonitorReset:
    @pytest.mark.asyncio
    async def test_prompt_change_resets_baseline(self) -> None:
        from myrm_agent_harness.infra.incremental.types import MonitorConfig, MonitorState

        mgr = _make_manager()
        mc = MonitorConfig(enabled=True, monitor_type="text_diff")
        job = _make_job(prompt="old prompt", monitor_config=mc)
        state = MonitorState(job_id="job-1", monitor_type="text_diff", data={"old": True})
        mgr._store.get_job = AsyncMock(return_value=job)
        mgr._store.get_monitor_state = AsyncMock(return_value=state)
        result = await mgr.update_job("job-1", "user-1", CronJobPatch(prompt="new prompt"))
        assert result is not None
        assert result.prompt == "new prompt"
        mgr._store.save_monitor_state.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_command_change_resets_baseline(self) -> None:
        from myrm_agent_harness.infra.incremental.types import MonitorConfig, MonitorState

        mgr = _make_manager()
        mc = MonitorConfig(enabled=True, monitor_type="text_diff")
        job = _make_job(job_type=JobType.SHELL, command="echo old", monitor_config=mc, prompt=None)
        state = MonitorState(job_id="job-1", monitor_type="text_diff", data={"old": True})
        mgr._store.get_job = AsyncMock(return_value=job)
        mgr._store.get_monitor_state = AsyncMock(return_value=state)
        result = await mgr.update_job("job-1", "user-1", CronJobPatch(command="echo new"))
        assert result is not None
        mgr._store.save_monitor_state.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_deduplicate_clear_resets_hash(self) -> None:
        mgr = _make_manager()
        job = _make_job(deduplicate=True, last_output_hash="abc123")
        mgr._store.get_job = AsyncMock(return_value=job)
        result = await mgr.update_job("job-1", "user-1", CronJobPatch(deduplicate=False))
        assert result is not None
        assert result.deduplicate is False
        assert result.last_output_hash is None

    @pytest.mark.asyncio
    async def test_clear_monitor_config(self) -> None:
        from myrm_agent_harness.infra.incremental.types import MonitorConfig

        mgr = _make_manager()
        mc = MonitorConfig(enabled=True, monitor_type="text_diff")
        job = _make_job(monitor_config=mc)
        mgr._store.get_job = AsyncMock(return_value=job)
        result = await mgr.update_job("job-1", "user-1", CronJobPatch(clear_monitor_config=True))
        assert result is not None
        assert result.monitor_config is None


# ---------------------------------------------------------------------------
# context_from validation & CRUD
# ---------------------------------------------------------------------------


class TestContextFrom:
    """Tests for context_from validation and CRUD integration."""

    @pytest.mark.asyncio
    async def test_validate_context_from_self_reference_rejected(self) -> None:
        """Self-referencing context_from must raise ValueError."""
        mgr = _make_manager()
        with pytest.raises(ValueError, match="must not reference the job itself"):
            await mgr._validate_context_from("job-1", ("job-1",))

    @pytest.mark.asyncio
    async def test_validate_context_from_nonexistent_rejected(self) -> None:
        """Referencing a non-existent job must raise ValueError."""
        mgr = _make_manager()
        mgr._store.get_job = AsyncMock(return_value=None)
        with pytest.raises(ValueError, match="non-existent job"):
            await mgr._validate_context_from("job-1", ("does-not-exist",))

    @pytest.mark.asyncio
    async def test_validate_context_from_valid(self) -> None:
        """Valid references should not raise."""
        mgr = _make_manager()
        ref_job = _make_job(id="ref-1")
        mgr._store.get_job = AsyncMock(return_value=ref_job)
        await mgr._validate_context_from("job-1", ("ref-1",))

    @pytest.mark.asyncio
    async def test_create_job_with_context_from(self) -> None:
        """Creating a job with context_from should persist the field."""
        mgr = _make_manager()
        ref_job = _make_job(id="ref-1")
        mgr._store.get_job = AsyncMock(return_value=ref_job)

        job = await mgr.create_job(
            user_id="user-1",
            name="Analyzer",
            job_type=JobType.AGENT,
            schedule=_make_schedule(),
            prompt="analyze data",
            context_from=("ref-1",),
        )
        assert job.context_from == ("ref-1",)

    @pytest.mark.asyncio
    async def test_create_job_with_invalid_context_from_rejected(self) -> None:
        """Creating a job with non-existent context_from should fail."""
        mgr = _make_manager()
        mgr._store.get_job = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match="non-existent job"):
            await mgr.create_job(
                user_id="user-1",
                name="Bad Ref",
                job_type=JobType.AGENT,
                schedule=_make_schedule(),
                prompt="test",
                context_from=("ghost-job",),
            )

    @pytest.mark.asyncio
    async def test_update_job_set_context_from(self) -> None:
        """Updating context_from should validate and persist."""
        mgr = _make_manager()
        existing = _make_job(context_from=())
        ref_job = _make_job(id="ref-1")

        async def mock_get(job_id: str) -> CronJob | None:
            if job_id == "job-1":
                return existing
            if job_id == "ref-1":
                return ref_job
            return None

        mgr._store.get_job = AsyncMock(side_effect=mock_get)
        result = await mgr.update_job("job-1", "user-1", CronJobPatch(context_from=("ref-1",)))
        assert result is not None
        assert result.context_from == ("ref-1",)

    @pytest.mark.asyncio
    async def test_update_job_clear_context_from(self) -> None:
        """clear_context_from should empty the field."""
        mgr = _make_manager()
        existing = _make_job(context_from=("ref-1",))
        mgr._store.get_job = AsyncMock(return_value=existing)
        result = await mgr.update_job("job-1", "user-1", CronJobPatch(clear_context_from=True))
        assert result is not None
        assert result.context_from == ()
