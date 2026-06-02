"""Test MonitorConfig integration in CronManager and CronJobPatch."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import pytest

from myrm_agent_harness.infra.incremental.types import MonitorConfig
from myrm_agent_harness.toolkits.cron.manager import CronManager
from myrm_agent_harness.toolkits.cron.types import (
    CronJob,
    CronJobPatch,
    JobType,
    Schedule,
    ScheduleKind,
)


@pytest.fixture
def mock_store():
    store = Mock()
    store.save_job = AsyncMock(side_effect=lambda j: j)
    store.get_job = AsyncMock(return_value=None)
    store.list_jobs = AsyncMock(return_value=[])
    store.delete_monitor_state = AsyncMock(return_value=True)
    store.get_monitor_state = AsyncMock(return_value=None)
    store.save_monitor_state = AsyncMock(return_value=None)
    return store


@pytest.fixture
def mock_scheduler():
    scheduler = Mock()
    scheduler.notify_change = Mock()
    return scheduler


@pytest.fixture
def manager(mock_store, mock_scheduler):
    return CronManager(
        store=mock_store,
        scheduler=mock_scheduler,
        shell_enabled=True,
    )


class TestMonitorConfigIntegration:
    """Test MonitorConfig creation and updates."""

    async def test_create_job_with_monitor_config(self, manager: CronManager):
        """Test creating a job with monitor_config."""
        job = await manager.create_job(
            user_id="user1",
            name="RSS Monitor",
            job_type=JobType.SHELL,
            schedule=Schedule(kind=ScheduleKind.INTERVAL, interval_ms=3600000),
            command="echo 'url1'",
            monitor_config=MonitorConfig(
                monitor_type="set",
                ttl_days=30,
                enabled=True,
            ),
        )

        assert job.monitor_config is not None
        assert job.monitor_config.monitor_type == "set"
        assert job.monitor_config.ttl_days == 30
        assert job.monitor_config.enabled is True

    async def test_create_job_without_monitor_config(self, manager: CronManager):
        """Test creating a job without monitor_config (default behavior)."""
        job = await manager.create_job(
            user_id="user1",
            name="Regular Job",
            job_type=JobType.SHELL,
            schedule=Schedule(kind=ScheduleKind.INTERVAL, interval_ms=3600000),
            command="echo 'test'",
        )

        assert job.monitor_config is None

    async def test_update_job_add_monitor_config(self, manager: CronManager, mock_store):
        """Test adding monitor_config to existing job."""
        existing_job = CronJob(
            id="job1",
            user_id="user1",
            name="Test Job",
            job_type=JobType.SHELL,
            schedule=Schedule(kind=ScheduleKind.INTERVAL, interval_ms=3600000),
            command="echo 'test'",
            monitor_config=None,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        mock_store.get_job.return_value = existing_job
        mock_store.save_job.side_effect = lambda j: j

        updated_job = await manager.update_job(
            "job1",
            "user1",
            CronJobPatch(
                monitor_config=MonitorConfig(
                    monitor_type="set",
                    ttl_days=7,
                    enabled=True,
                )
            ),
        )

        assert updated_job is not None
        assert updated_job.monitor_config is not None
        assert updated_job.monitor_config.ttl_days == 7

    async def test_update_job_modify_monitor_config(self, manager: CronManager, mock_store):
        """Test modifying existing monitor_config."""
        existing_job = CronJob(
            id="job1",
            user_id="user1",
            name="Test Job",
            job_type=JobType.SHELL,
            schedule=Schedule(kind=ScheduleKind.INTERVAL, interval_ms=3600000),
            command="echo 'test'",
            monitor_config=MonitorConfig(
                monitor_type="set",
                ttl_days=30,
                enabled=True,
            ),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        mock_store.get_job.return_value = existing_job
        mock_store.save_job.side_effect = lambda j: j

        updated_job = await manager.update_job(
            "job1",
            "user1",
            CronJobPatch(
                monitor_config=MonitorConfig(
                    monitor_type="set",
                    ttl_days=90,
                    enabled=True,
                )
            ),
        )

        assert updated_job is not None
        assert updated_job.monitor_config is not None
        assert updated_job.monitor_config.ttl_days == 90

    async def test_update_job_clear_monitor_config(self, manager: CronManager, mock_store):
        """Test clearing monitor_config."""
        existing_job = CronJob(
            id="job1",
            user_id="user1",
            name="Test Job",
            job_type=JobType.SHELL,
            schedule=Schedule(kind=ScheduleKind.INTERVAL, interval_ms=3600000),
            command="echo 'test'",
            monitor_config=MonitorConfig(
                monitor_type="set",
                ttl_days=30,
                enabled=True,
            ),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        mock_store.get_job.return_value = existing_job
        mock_store.save_job.side_effect = lambda j: j

        updated_job = await manager.update_job(
            "job1",
            "user1",
            CronJobPatch(clear_monitor_config=True),
        )

        assert updated_job is not None
        assert updated_job.monitor_config is None

    async def test_reset_monitor_baseline(self, manager: CronManager, mock_store):
        """Test manual baseline reset."""
        from myrm_agent_harness.infra.incremental.types import MonitorState

        existing_job = CronJob(
            id="job1",
            user_id="user1",
            name="Test Job",
            job_type=JobType.SHELL,
            schedule=Schedule(kind=ScheduleKind.INTERVAL, interval_ms=3600000),
            command="echo 'test'",
            monitor_config=MonitorConfig(
                monitor_type="set",
                ttl_days=30,
                enabled=True,
            ),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        existing_state = MonitorState(
            job_id="job1",
            monitor_type="set",
            data={"seen": ["url1", "url2"]},
            ttl_days=30,
        )

        mock_store.get_job.return_value = existing_job
        mock_store.get_monitor_state.return_value = existing_state
        mock_store.save_monitor_state.return_value = None

        reset = await manager.reset_monitor_baseline("job1", "user1")

        assert reset is True
        mock_store.get_monitor_state.assert_called_once_with("job1")
        mock_store.save_monitor_state.assert_called_once()

        saved_state = mock_store.save_monitor_state.call_args[0][0]
        assert saved_state.data == {}
        assert saved_state.last_reset_at is not None
        assert saved_state.last_reset_reason == "manual"

    async def test_reset_baseline_wrong_user(self, manager: CronManager, mock_store):
        """Test baseline reset fails for wrong user."""
        existing_job = CronJob(
            id="job1",
            user_id="user1",
            name="Test Job",
            job_type=JobType.SHELL,
            schedule=Schedule(kind=ScheduleKind.INTERVAL, interval_ms=3600000),
            command="echo 'test'",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        mock_store.get_job.return_value = existing_job

        reset = await manager.reset_monitor_baseline("job1", "wrong_user")

        assert reset is False
        mock_store.delete_monitor_state.assert_not_called()

    async def test_auto_reset_baseline_on_command_change(self, manager: CronManager, mock_store):
        """Test baseline auto-resets when command changes with enabled monitor."""
        from myrm_agent_harness.infra.incremental.types import MonitorState

        existing_job = CronJob(
            id="job1",
            user_id="user1",
            name="RSS Monitor",
            job_type=JobType.SHELL,
            schedule=Schedule(kind=ScheduleKind.INTERVAL, interval_ms=3600000),
            command="echo 'url1'",
            monitor_config=MonitorConfig(
                monitor_type="set",
                ttl_days=30,
                enabled=True,
            ),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        existing_state = MonitorState(
            job_id="job1",
            monitor_type="set",
            data={"seen": ["url1"]},
            ttl_days=30,
        )

        mock_store.get_job.return_value = existing_job
        mock_store.save_job.return_value = existing_job
        mock_store.get_monitor_state.return_value = existing_state
        mock_store.save_monitor_state.return_value = None

        patch = CronJobPatch(command="echo 'url2'")
        await manager.update_job("job1", "user1", patch)

        mock_store.get_monitor_state.assert_called_once_with("job1")
        mock_store.save_monitor_state.assert_called_once()
        saved_state = mock_store.save_monitor_state.call_args[0][0]
        assert saved_state.data == {}
        assert saved_state.last_reset_at is not None
        assert saved_state.last_reset_reason == "command_change"

    async def test_auto_reset_baseline_on_prompt_change(self, manager: CronManager, mock_store):
        """Test baseline auto-resets when prompt changes with enabled monitor."""
        from myrm_agent_harness.infra.incremental.types import MonitorState

        existing_job = CronJob(
            id="job1",
            user_id="user1",
            name="AI Task",
            job_type=JobType.AGENT,
            schedule=Schedule(kind=ScheduleKind.INTERVAL, interval_ms=3600000),
            prompt="Analyze data",
            monitor_config=MonitorConfig(
                monitor_type="set",
                ttl_days=30,
                enabled=True,
            ),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        existing_state = MonitorState(
            job_id="job1",
            monitor_type="set",
            data={"seen": ["item1"]},
            ttl_days=30,
        )

        mock_store.get_job.return_value = existing_job
        mock_store.save_job.return_value = existing_job
        mock_store.get_monitor_state.return_value = existing_state
        mock_store.save_monitor_state.return_value = None

        patch = CronJobPatch(prompt="Analyze new data")
        await manager.update_job("job1", "user1", patch)

        mock_store.get_monitor_state.assert_called_once_with("job1")
        mock_store.save_monitor_state.assert_called_once()
        saved_state = mock_store.save_monitor_state.call_args[0][0]
        assert saved_state.data == {}
        assert saved_state.last_reset_at is not None
        assert saved_state.last_reset_reason == "prompt_change"

    async def test_no_reset_when_monitor_disabled(self, manager: CronManager, mock_store):
        """Test no baseline reset when monitor is disabled."""
        existing_job = CronJob(
            id="job1",
            user_id="user1",
            name="Job",
            job_type=JobType.SHELL,
            schedule=Schedule(kind=ScheduleKind.INTERVAL, interval_ms=3600000),
            command="echo 'old'",
            monitor_config=MonitorConfig(
                monitor_type="set",
                ttl_days=30,
                enabled=False,
            ),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        mock_store.get_job.return_value = existing_job
        mock_store.save_job.return_value = existing_job

        patch = CronJobPatch(command="echo 'new'")
        await manager.update_job("job1", "user1", patch)

        mock_store.delete_monitor_state.assert_not_called()

    async def test_no_reset_when_command_unchanged(self, manager: CronManager, mock_store):
        """Test no baseline reset when command is unchanged."""
        existing_job = CronJob(
            id="job1",
            user_id="user1",
            name="Job",
            job_type=JobType.SHELL,
            schedule=Schedule(kind=ScheduleKind.INTERVAL, interval_ms=3600000),
            command="echo 'same'",
            monitor_config=MonitorConfig(
                monitor_type="set",
                ttl_days=30,
                enabled=True,
            ),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        mock_store.get_job.return_value = existing_job
        mock_store.save_job.return_value = existing_job

        patch = CronJobPatch(command="echo 'same'")
        await manager.update_job("job1", "user1", patch)

        mock_store.delete_monitor_state.assert_not_called()

    async def test_auto_reset_without_existing_state(self, manager: CronManager, mock_store):
        """Test auto-reset calls delete when no existing state."""
        existing_job = CronJob(
            id="job1",
            user_id="user1",
            name="Job",
            job_type=JobType.SHELL,
            schedule=Schedule(kind=ScheduleKind.INTERVAL, interval_ms=3600000),
            command="echo 'old'",
            monitor_config=MonitorConfig(
                monitor_type="set",
                ttl_days=30,
                enabled=True,
            ),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        mock_store.get_job.return_value = existing_job
        mock_store.save_job.return_value = existing_job
        mock_store.get_monitor_state.return_value = None

        patch = CronJobPatch(command="echo 'new'")
        await manager.update_job("job1", "user1", patch)

        mock_store.get_monitor_state.assert_called_once_with("job1")
        mock_store.save_monitor_state.assert_not_called()
        mock_store.delete_monitor_state.assert_called_once_with("job1")

    async def test_auto_reset_on_both_command_and_prompt_change(self, manager: CronManager, mock_store):
        """Test that command_change takes priority when both command and prompt change."""
        from myrm_agent_harness.infra.incremental.types import MonitorState

        existing_job = CronJob(
            id="job1",
            user_id="user1",
            name="Agent Job",
            job_type=JobType.AGENT,
            schedule=Schedule(kind=ScheduleKind.INTERVAL, interval_ms=3600000),
            prompt="Analyze data",
            command="echo 'old'",
            monitor_config=MonitorConfig(
                monitor_type="set",
                ttl_days=30,
                enabled=True,
            ),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        existing_state = MonitorState(
            job_id="job1",
            monitor_type="set",
            data={"seen": ["item1"]},
            ttl_days=30,
        )

        mock_store.get_job.return_value = existing_job
        mock_store.save_job.return_value = existing_job
        mock_store.get_monitor_state.return_value = existing_state
        mock_store.save_monitor_state.return_value = None

        patch = CronJobPatch(command="echo 'new'", prompt="Analyze new data")
        await manager.update_job("job1", "user1", patch)

        mock_store.save_monitor_state.assert_called_once()
        saved_state = mock_store.save_monitor_state.call_args[0][0]
        assert saved_state.data == {}
        assert saved_state.last_reset_reason == "command_change"

    async def test_reset_failure_does_not_block_job_update(self, manager: CronManager, mock_store):
        """Test that job update succeeds even when baseline reset fails."""
        existing_job = CronJob(
            id="job1",
            user_id="user1",
            name="Job",
            job_type=JobType.SHELL,
            schedule=Schedule(kind=ScheduleKind.INTERVAL, interval_ms=3600000),
            command="echo 'old'",
            monitor_config=MonitorConfig(
                monitor_type="set",
                ttl_days=30,
                enabled=True,
            ),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        mock_store.get_job.return_value = existing_job
        mock_store.save_job.return_value = existing_job
        mock_store.get_monitor_state.side_effect = RuntimeError("DB connection lost")

        patch = CronJobPatch(command="echo 'new'")
        updated_job = await manager.update_job("job1", "user1", patch)

        assert updated_job is not None
        assert updated_job.command == "echo 'new'"
        mock_store.save_job.assert_called_once()

    async def test_auto_reset_on_monitor_type_change(self, manager: CronManager, mock_store):
        """Test baseline resets when monitor_type changes (e.g. set → hash)."""
        from myrm_agent_harness.infra.incremental.types import MonitorState

        existing_job = CronJob(
            id="job1",
            user_id="user1",
            name="Job",
            job_type=JobType.SHELL,
            schedule=Schedule(kind=ScheduleKind.INTERVAL, interval_ms=3600000),
            command="echo 'test'",
            monitor_config=MonitorConfig(
                monitor_type="set",
                ttl_days=30,
                enabled=True,
            ),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        existing_state = MonitorState(
            job_id="job1",
            monitor_type="set",
            data={"seen": ["url1"]},
            ttl_days=30,
        )

        mock_store.get_job.return_value = existing_job
        mock_store.save_job.return_value = existing_job
        mock_store.get_monitor_state.return_value = existing_state
        mock_store.save_monitor_state.return_value = None

        patch = CronJobPatch(monitor_config=MonitorConfig(monitor_type="hash", ttl_days=30, enabled=True))
        await manager.update_job("job1", "user1", patch)

        mock_store.save_monitor_state.assert_called_once()
        saved_state = mock_store.save_monitor_state.call_args[0][0]
        assert saved_state.data == {}
        assert saved_state.last_reset_reason == "monitor_type_change"

    async def test_no_reset_when_monitor_type_unchanged(self, manager: CronManager, mock_store):
        """Test no baseline reset when monitor_type stays the same."""
        existing_job = CronJob(
            id="job1",
            user_id="user1",
            name="Job",
            job_type=JobType.SHELL,
            schedule=Schedule(kind=ScheduleKind.INTERVAL, interval_ms=3600000),
            command="echo 'test'",
            monitor_config=MonitorConfig(
                monitor_type="set",
                ttl_days=30,
                enabled=True,
            ),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        mock_store.get_job.return_value = existing_job
        mock_store.save_job.return_value = existing_job

        patch = CronJobPatch(monitor_config=MonitorConfig(monitor_type="set", ttl_days=90, enabled=True))
        await manager.update_job("job1", "user1", patch)

        mock_store.save_monitor_state.assert_not_called()

    async def test_delete_job_calls_cascade(self, manager: CronManager, mock_store):
        """Test that delete_job delegates to delete_job_cascade."""
        existing_job = CronJob(
            id="job1",
            user_id="user1",
            name="Job",
            job_type=JobType.SHELL,
            schedule=Schedule(kind=ScheduleKind.INTERVAL, interval_ms=3600000),
            command="echo 'test'",
            monitor_config=MonitorConfig(
                monitor_type="set",
                ttl_days=30,
                enabled=True,
            ),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        mock_store.get_job.return_value = existing_job
        mock_store.delete_job_cascade = AsyncMock(return_value=True)

        deleted = await manager.delete_job("job1", "user1")

        assert deleted is True
        mock_store.delete_job_cascade.assert_called_once_with("job1")
