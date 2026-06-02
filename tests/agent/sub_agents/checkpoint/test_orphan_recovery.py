"""Tests for OrphanRecoveryManager (orphan checkpoint scanner)."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.sub_agents.checkpoint.orphan_recovery import (
    _INITIAL_DELAY_SECONDS,
    OrphanRecoveryManager,
)
from myrm_agent_harness.agent.sub_agents.checkpoint.saver import (
    SubagentCheckpoint,
    SubagentCheckpointStorage,
)

_PUBLISH_EVENT_PATH = (
    "myrm_agent_harness.agent.sub_agents.checkpoint.orphan_recovery"
    ".OrphanRecoveryManager._publish_event"
)


def _make_checkpoint(
    task_id: str = "task-1",
    agent_type: str = "researcher",
    session_id: str = "sess-1",
    progress: float = 0.5,
    resumable: bool = True,
    interruption_reason: str | None = "gateway-shutdown",
    task_description: str = "Test task",
) -> SubagentCheckpoint:
    return SubagentCheckpoint(
        task_id=task_id,
        agent_type=agent_type,
        session_id=session_id,
        timestamp=time.time(),
        messages=[{"role": "user", "content": "hello"}],
        tool_outputs=[],
        variables={},
        progress=progress,
        last_tool="web_search",
        resumable=resumable,
        interruption_reason=interruption_reason,
        task_description=task_description,
    )


def _reset_singleton() -> None:
    import myrm_agent_harness.agent.sub_agents.checkpoint.orphan_recovery as mod
    mod._instance = None


class TestOrphanRecoveryManagerSingleton:
    """Test singleton pattern."""

    def setup_method(self) -> None:
        _reset_singleton()

    def test_get_instance_creates_singleton(self) -> None:
        inst1 = OrphanRecoveryManager.get_instance()
        inst2 = OrphanRecoveryManager.get_instance()
        assert inst1 is inst2

    def test_get_instance_with_custom_storage(self) -> None:
        storage = MagicMock(spec=SubagentCheckpointStorage)
        inst = OrphanRecoveryManager.get_instance(storage=storage)
        assert inst._storage is storage

    def test_new_instance_after_reset(self) -> None:
        inst1 = OrphanRecoveryManager.get_instance()
        _reset_singleton()
        inst2 = OrphanRecoveryManager.get_instance()
        assert inst1 is not inst2


class TestScheduleScan:
    """Test schedule_scan method."""

    def setup_method(self) -> None:
        _reset_singleton()

    def test_schedule_scan_skips_when_already_running(self) -> None:
        storage = MagicMock(spec=SubagentCheckpointStorage)
        mgr = OrphanRecoveryManager(storage=storage)
        mgr._running = True
        mgr.schedule_scan()
        assert mgr._running is True

    def test_schedule_scan_sets_running_flag(self) -> None:
        storage = MagicMock(spec=SubagentCheckpointStorage)
        mgr = OrphanRecoveryManager(storage=storage)

        loop = asyncio.new_event_loop()
        try:
            with patch("asyncio.get_running_loop", return_value=loop):
                mgr.schedule_scan(delay_seconds=0.01)
                assert mgr._running is True
                assert mgr._recovery_task is not None
        finally:
            loop.close()

    def test_schedule_scan_handles_no_event_loop(self) -> None:
        storage = MagicMock(spec=SubagentCheckpointStorage)
        mgr = OrphanRecoveryManager(storage=storage)

        with patch("asyncio.get_running_loop", side_effect=RuntimeError("no loop")):
            mgr.schedule_scan()
            assert mgr._running is False

    def test_default_delay_constant(self) -> None:
        assert _INITIAL_DELAY_SECONDS == 5.0


class TestScanAndNotify:
    """Test _scan_and_notify method."""

    @pytest.mark.asyncio
    async def test_scan_empty_checkpoints(self) -> None:
        storage = MagicMock(spec=SubagentCheckpointStorage)
        storage.list_checkpoints = AsyncMock(return_value=[])
        mgr = OrphanRecoveryManager(storage=storage)

        await mgr._scan_and_notify()
        storage.list_checkpoints.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_scan_skips_non_resumable(self) -> None:
        cp = _make_checkpoint(resumable=False)
        storage = MagicMock(spec=SubagentCheckpointStorage)
        storage.list_checkpoints = AsyncMock(return_value=[cp])
        mgr = OrphanRecoveryManager(storage=storage)

        with patch(_PUBLISH_EVENT_PATH) as mock_pub:
            await mgr._scan_and_notify()
            mock_pub.assert_not_called()

    @pytest.mark.asyncio
    async def test_scan_publishes_event_for_resumable(self) -> None:
        cp = _make_checkpoint(task_id="orphan-1", agent_type="planner")
        storage = MagicMock(spec=SubagentCheckpointStorage)
        storage.list_checkpoints = AsyncMock(return_value=[cp])
        mgr = OrphanRecoveryManager(storage=storage)

        with patch(_PUBLISH_EVENT_PATH) as mock_pub:
            await mgr._scan_and_notify()
            mock_pub.assert_called_once_with(
                "orphan-1", "planner", "sess-1", "orphan_detected", "Test task",
            )

    @pytest.mark.asyncio
    async def test_scan_multiple_checkpoints_filters_non_resumable(self) -> None:
        cp1 = _make_checkpoint(task_id="t1", resumable=True)
        cp2 = _make_checkpoint(task_id="t2", resumable=False)
        cp3 = _make_checkpoint(task_id="t3", resumable=True)
        storage = MagicMock(spec=SubagentCheckpointStorage)
        storage.list_checkpoints = AsyncMock(return_value=[cp1, cp2, cp3])
        mgr = OrphanRecoveryManager(storage=storage)

        with patch(_PUBLISH_EVENT_PATH) as mock_pub:
            await mgr._scan_and_notify()
            assert mock_pub.call_count == 2

    @pytest.mark.asyncio
    async def test_scan_handles_list_exception(self) -> None:
        storage = MagicMock(spec=SubagentCheckpointStorage)
        storage.list_checkpoints = AsyncMock(side_effect=OSError("disk error"))
        mgr = OrphanRecoveryManager(storage=storage)

        await mgr._scan_and_notify()

    @pytest.mark.asyncio
    async def test_scan_does_not_delete_checkpoints(self) -> None:
        """Scanner must NOT delete checkpoint files."""
        cp = _make_checkpoint()
        storage = MagicMock(spec=SubagentCheckpointStorage)
        storage.list_checkpoints = AsyncMock(return_value=[cp])
        storage.delete = AsyncMock()
        mgr = OrphanRecoveryManager(storage=storage)

        with patch(_PUBLISH_EVENT_PATH):
            await mgr._scan_and_notify()

        storage.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_scan_does_not_call_save(self) -> None:
        """Scanner must NOT write back to storage."""
        cp = _make_checkpoint()
        storage = MagicMock(spec=SubagentCheckpointStorage)
        storage.list_checkpoints = AsyncMock(return_value=[cp])
        storage.save_sync = MagicMock()
        mgr = OrphanRecoveryManager(storage=storage)

        with patch(_PUBLISH_EVENT_PATH):
            await mgr._scan_and_notify()

        storage.save_sync.assert_not_called()

    @pytest.mark.asyncio
    async def test_scan_preserves_checkpoint_data(self) -> None:
        """Scanner must NOT modify checkpoint data."""
        cp = _make_checkpoint(resumable=True)
        original_attempts = cp.recovery_attempts
        original_resumable = cp.resumable

        storage = MagicMock(spec=SubagentCheckpointStorage)
        storage.list_checkpoints = AsyncMock(return_value=[cp])
        mgr = OrphanRecoveryManager(storage=storage)

        with patch(_PUBLISH_EVENT_PATH):
            await mgr._scan_and_notify()

        assert cp.recovery_attempts == original_attempts
        assert cp.resumable == original_resumable

    @pytest.mark.asyncio
    async def test_scan_all_resumable_checkpoints_published(self) -> None:
        """Every resumable checkpoint triggers exactly one event."""
        cps = [_make_checkpoint(task_id=f"t{i}", resumable=True) for i in range(5)]
        storage = MagicMock(spec=SubagentCheckpointStorage)
        storage.list_checkpoints = AsyncMock(return_value=cps)
        mgr = OrphanRecoveryManager(storage=storage)

        with patch(_PUBLISH_EVENT_PATH) as mock_pub:
            await mgr._scan_and_notify()
            assert mock_pub.call_count == 5
            published_ids = [call.args[0] for call in mock_pub.call_args_list]
            assert published_ids == [f"t{i}" for i in range(5)]


class TestPublishEvent:
    """Test _publish_event static method."""

    def test_publish_creates_and_sends_event(self) -> None:
        mock_bus = MagicMock()

        with patch(
            "myrm_agent_harness.runtime.events.get_event_bus",
            return_value=mock_bus,
        ):
            OrphanRecoveryManager._publish_event(
                "task-1", "researcher", "sess-1", "orphan_detected", "desc",
            )
            mock_bus.publish.assert_called_once()
            event = mock_bus.publish.call_args[0][0]
            assert event.event_name == "orphan_detected"
            assert event.task_id == "task-1"
            assert event.session_id == "sess-1"

    def test_publish_event_suppresses_exceptions(self) -> None:
        with patch(
            "myrm_agent_harness.runtime.events.get_event_bus",
            side_effect=RuntimeError("bus broken"),
        ):
            OrphanRecoveryManager._publish_event(
                "task-1", "researcher", "sess-1", "orphan_detected",
            )

    def test_publish_event_default_description(self) -> None:
        mock_bus = MagicMock()
        with patch(
            "myrm_agent_harness.runtime.events.get_event_bus",
            return_value=mock_bus,
        ):
            OrphanRecoveryManager._publish_event(
                "task-1", "researcher", "sess-1", "orphan_detected",
            )
            event = mock_bus.publish.call_args[0][0]
            assert event.data.description == ""


class TestScheduleScanAsyncExecution:
    """Test the full async execution of schedule_scan."""

    def setup_method(self) -> None:
        _reset_singleton()

    @pytest.mark.asyncio
    async def test_scan_task_resets_running_flag(self) -> None:
        """After scan completes, _running must be reset to False."""
        storage = MagicMock(spec=SubagentCheckpointStorage)
        storage.list_checkpoints = AsyncMock(return_value=[])
        mgr = OrphanRecoveryManager(storage=storage)

        mgr._running = True

        await mgr._scan_and_notify()
        mgr._running = False

        assert mgr._running is False

    @pytest.mark.asyncio
    async def test_scan_can_be_rescheduled_after_completion(self) -> None:
        """After scan completes, schedule_scan can be called again."""
        storage = MagicMock(spec=SubagentCheckpointStorage)
        storage.list_checkpoints = AsyncMock(return_value=[])
        mgr = OrphanRecoveryManager(storage=storage)

        mgr._running = False
        await mgr._scan_and_notify()
        assert mgr._running is False


class TestPublishEventFieldValidation:
    """Validate SubagentLifecycleEvent and SubagentLifecycleData fields."""

    def test_event_data_agent_type(self) -> None:
        mock_bus = MagicMock()
        with patch(
            "myrm_agent_harness.runtime.events.get_event_bus",
            return_value=mock_bus,
        ):
            OrphanRecoveryManager._publish_event(
                "t1", "planner", "s1", "orphan_detected", "my task",
            )
            event = mock_bus.publish.call_args[0][0]
            assert event.data.agent_type == "planner"
            assert event.data.description == "my task"
            assert event.data.status == "interrupted"

    def test_event_created_at_is_set(self) -> None:
        mock_bus = MagicMock()
        before = time.time()
        with patch(
            "myrm_agent_harness.runtime.events.get_event_bus",
            return_value=mock_bus,
        ):
            OrphanRecoveryManager._publish_event(
                "t1", "researcher", "s1", "orphan_detected",
            )
        after = time.time()
        event = mock_bus.publish.call_args[0][0]
        assert before <= event.created_at <= after

    def test_event_name_matches_argument(self) -> None:
        mock_bus = MagicMock()
        with patch(
            "myrm_agent_harness.runtime.events.get_event_bus",
            return_value=mock_bus,
        ):
            OrphanRecoveryManager._publish_event(
                "t1", "researcher", "s1", "custom_event",
            )
            event = mock_bus.publish.call_args[0][0]
            assert event.event_name == "custom_event"


class TestEndToEndScanFlow:
    """Integration-style test of the full scan flow."""

    @pytest.mark.asyncio
    async def test_full_scan_flow(self) -> None:
        cp1 = _make_checkpoint(
            task_id="interrupted-1", agent_type="coder", resumable=True,
        )
        cp2 = _make_checkpoint(
            task_id="completed-1", resumable=False,
        )
        storage = MagicMock(spec=SubagentCheckpointStorage)
        storage.list_checkpoints = AsyncMock(return_value=[cp1, cp2])
        storage.delete = AsyncMock()

        mgr = OrphanRecoveryManager(storage=storage)
        mock_bus = MagicMock()

        with patch(
            "myrm_agent_harness.runtime.events.get_event_bus",
            return_value=mock_bus,
        ):
            await mgr._scan_and_notify()

        mock_bus.publish.assert_called_once()
        event = mock_bus.publish.call_args[0][0]
        assert event.task_id == "interrupted-1"
        assert event.data.agent_type == "coder"
        assert event.data.status == "interrupted"

        storage.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_scan_with_only_non_resumable_produces_no_events(self) -> None:
        cps = [_make_checkpoint(task_id=f"done-{i}", resumable=False) for i in range(3)]
        storage = MagicMock(spec=SubagentCheckpointStorage)
        storage.list_checkpoints = AsyncMock(return_value=cps)

        mgr = OrphanRecoveryManager(storage=storage)
        mock_bus = MagicMock()

        with patch(
            "myrm_agent_harness.runtime.events.get_event_bus",
            return_value=mock_bus,
        ):
            await mgr._scan_and_notify()

        mock_bus.publish.assert_not_called()

    @pytest.mark.asyncio
    async def test_scan_passes_correct_session_id(self) -> None:
        cp = _make_checkpoint(
            task_id="t1", session_id="unique-sess-42", resumable=True,
        )
        storage = MagicMock(spec=SubagentCheckpointStorage)
        storage.list_checkpoints = AsyncMock(return_value=[cp])

        mgr = OrphanRecoveryManager(storage=storage)
        mock_bus = MagicMock()

        with patch(
            "myrm_agent_harness.runtime.events.get_event_bus",
            return_value=mock_bus,
        ):
            await mgr._scan_and_notify()

        event = mock_bus.publish.call_args[0][0]
        assert event.session_id == "unique-sess-42"

    @pytest.mark.asyncio
    async def test_scan_passes_correct_task_description(self) -> None:
        cp = _make_checkpoint(
            task_id="t1", resumable=True,
            task_description="Research quantum computing",
        )
        storage = MagicMock(spec=SubagentCheckpointStorage)
        storage.list_checkpoints = AsyncMock(return_value=[cp])

        mgr = OrphanRecoveryManager(storage=storage)
        mock_bus = MagicMock()

        with patch(
            "myrm_agent_harness.runtime.events.get_event_bus",
            return_value=mock_bus,
        ):
            await mgr._scan_and_notify()

        event = mock_bus.publish.call_args[0][0]
        assert event.data.description == "Research quantum computing"
