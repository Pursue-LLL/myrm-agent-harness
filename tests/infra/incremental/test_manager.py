"""Unit tests for IncrementalMonitorManager."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock

import pytest

from myrm_agent_harness.infra.incremental.hash_monitor import HashMonitor
from myrm_agent_harness.infra.incremental.manager import IncrementalMonitorManager
from myrm_agent_harness.infra.incremental.set_monitor import SetMonitor
from myrm_agent_harness.infra.incremental.types import MonitorConfig, MonitorState


class TestIncrementalMonitorManager:
    """Test IncrementalMonitorManager lifecycle and TTL."""

    @pytest.fixture
    def mock_store(self) -> Mock:
        """Create mock CronStore."""
        store = Mock()
        store.get_monitor_state = AsyncMock(return_value=None)
        store.save_monitor_state = AsyncMock()
        return store

    @pytest.fixture
    def manager(self, mock_store: Mock) -> IncrementalMonitorManager:
        """Create manager with mock store."""
        return IncrementalMonitorManager(mock_store)

    async def test_get_monitor_creates_new_on_first_call(
        self,
        manager: IncrementalMonitorManager,
        mock_store: Mock,
    ) -> None:
        """First call should create new monitor."""
        config = MonitorConfig(monitor_type="set", ttl_days=30)

        monitor, reset_reason = await manager.get_monitor("job1", config)

        assert isinstance(monitor, SetMonitor)
        assert monitor.is_baseline()
        assert reset_reason == "first_run"
        mock_store.get_monitor_state.assert_called_once_with("job1")

    async def test_get_monitor_restores_from_state(
        self,
        manager: IncrementalMonitorManager,
        mock_store: Mock,
    ) -> None:
        """Should restore monitor from persisted state."""
        state = MonitorState(
            job_id="job1",
            monitor_type="set",
            data={"seen": ["url1", "url2"], "is_baseline": False},
            updated_at=datetime.now(UTC),
            ttl_days=30,
        )
        mock_store.get_monitor_state.return_value = state

        config = MonitorConfig(monitor_type="set", ttl_days=30)
        monitor, _ = await manager.get_monitor("job1", config)

        assert isinstance(monitor, SetMonitor)
        assert not monitor.is_baseline()

        delta = monitor.compute_delta("url1\nurl2\nurl3")
        assert delta == "url3"

    async def test_get_monitor_supports_hash_type(
        self,
        manager: IncrementalMonitorManager,
        mock_store: Mock,
    ) -> None:
        """Hash monitor should be created/restored without errors."""
        state = MonitorState(
            job_id="job-hash",
            monitor_type="hash",
            data={"last_hash": "abc123", "is_baseline": False},
            updated_at=datetime.now(UTC),
            ttl_days=30,
        )
        mock_store.get_monitor_state.return_value = state

        config = MonitorConfig(monitor_type="hash", ttl_days=30)
        monitor, reset_reason = await manager.get_monitor("job-hash", config)

        assert isinstance(monitor, HashMonitor)
        assert reset_reason is None

    async def test_get_monitor_caches_instances(
        self,
        manager: IncrementalMonitorManager,
        mock_store: Mock,
    ) -> None:
        """Should cache monitor instances."""
        config = MonitorConfig(monitor_type="set", ttl_days=30)

        monitor1, _ = await manager.get_monitor("job1", config)
        monitor2, reset_reason2 = await manager.get_monitor("job1", config)

        assert monitor1 is monitor2
        assert reset_reason2 is None
        mock_store.get_monitor_state.assert_called_once()

    async def test_expired_state_resets_baseline(
        self,
        manager: IncrementalMonitorManager,
        mock_store: Mock,
    ) -> None:
        """Expired state should reset to baseline."""
        expired_state = MonitorState(
            job_id="job1",
            monitor_type="set",
            data={"seen": ["url1", "url2"], "is_baseline": False},
            updated_at=datetime.now(UTC) - timedelta(days=31),
            ttl_days=30,
        )
        mock_store.get_monitor_state.return_value = expired_state

        config = MonitorConfig(monitor_type="set", ttl_days=30)
        monitor, reset_reason = await manager.get_monitor("job1", config)

        assert monitor.is_baseline()
        assert reset_reason == "ttl_expired"

    async def test_save_monitor_state_persists_to_store(
        self,
        manager: IncrementalMonitorManager,
        mock_store: Mock,
    ) -> None:
        """Should persist monitor state to store."""
        config = MonitorConfig(monitor_type="set", ttl_days=30)
        monitor, _ = await manager.get_monitor("job1", config)

        monitor.compute_delta("url1\nurl2")
        monitor.update_baseline("url1\nurl2")

        await manager.save_monitor_state("job1", monitor, config)

        mock_store.save_monitor_state.assert_called_once()
        saved_state = mock_store.save_monitor_state.call_args[0][0]
        assert saved_state.job_id == "job1"
        assert saved_state.monitor_type == "set"
        assert "url1" in saved_state.data["seen"]
        assert "url2" in saved_state.data["seen"]

    async def test_save_hash_monitor_state_persists_to_store(
        self,
        manager: IncrementalMonitorManager,
        mock_store: Mock,
    ) -> None:
        """Hash monitor state should be persisted the same way as set monitor."""
        config = MonitorConfig(monitor_type="hash", ttl_days=30)
        monitor, _ = await manager.get_monitor("job-hash", config)

        monitor.compute_delta('{"asset":"BTC","price":67000}')
        monitor.update_baseline("")

        await manager.save_monitor_state("job-hash", monitor, config)

        mock_store.save_monitor_state.assert_called_once()
        saved_state = mock_store.save_monitor_state.call_args[0][0]
        assert saved_state.job_id == "job-hash"
        assert saved_state.monitor_type == "hash"
        assert isinstance(saved_state.data.get("last_hash"), str)
        assert saved_state.data.get("is_baseline") is False

    async def test_clear_cache_single_job(
        self,
        manager: IncrementalMonitorManager,
    ) -> None:
        """Should clear cache for single job."""
        config = MonitorConfig(monitor_type="set", ttl_days=30)

        await manager.get_monitor("job1", config)
        await manager.get_monitor("job2", config)

        manager.clear_cache("job1")

        assert "job1" not in manager._cache
        assert "job2" in manager._cache

    async def test_clear_cache_all_jobs(
        self,
        manager: IncrementalMonitorManager,
    ) -> None:
        """Should clear cache for all jobs."""
        config = MonitorConfig(monitor_type="set", ttl_days=30)

        await manager.get_monitor("job1", config)
        await manager.get_monitor("job2", config)

        manager.clear_cache()

        assert len(manager._cache) == 0

    async def test_unsupported_monitor_type_raises(
        self,
        manager: IncrementalMonitorManager,
    ) -> None:
        """Unsupported monitor type should raise ValueError."""
        config = MonitorConfig(monitor_type="unsupported", ttl_days=30)

        with pytest.raises(ValueError, match="Unsupported monitor type"):
            await manager.get_monitor("job1", config)

    async def test_record_monitor_failure_increments_count(self) -> None:
        """Recording failures should increment failure count."""
        storage: dict[str, MonitorState] = {}

        store = Mock()
        store.get_monitor_state = AsyncMock(side_effect=lambda job_id: storage.get(job_id))
        store.save_monitor_state = AsyncMock(side_effect=lambda state: storage.update({state.job_id: state}))

        manager = IncrementalMonitorManager(store)
        config = MonitorConfig(monitor_type="set", ttl_days=30)
        error = ValueError("Test error")

        count1 = await manager.record_monitor_failure("job1", config, error)
        assert count1 == 1
        assert storage["job1"].failure_count == 1

        count2 = await manager.record_monitor_failure("job1", config, error)
        assert count2 == 2
        assert storage["job1"].failure_count == 2

        count3 = await manager.record_monitor_failure("job1", config, error)
        assert count3 == 3
        assert storage["job1"].failure_count == 3

    async def test_successful_save_resets_failure_count(self) -> None:
        """Successful monitoring should reset failure count to 0."""
        storage: dict[str, MonitorState] = {}

        store = Mock()
        store.get_monitor_state = AsyncMock(side_effect=lambda job_id: storage.get(job_id))
        store.save_monitor_state = AsyncMock(side_effect=lambda state: storage.update({state.job_id: state}))

        manager = IncrementalMonitorManager(store)
        config = MonitorConfig(monitor_type="set", ttl_days=30)

        await manager.record_monitor_failure("job1", config, ValueError("Test"))
        assert storage["job1"].failure_count == 1

        monitor, _ = await manager.get_monitor("job1", config)
        await manager.save_monitor_state("job1", monitor, config)

        assert storage["job1"].failure_count == 0
        assert storage["job1"].last_failure_at is None
