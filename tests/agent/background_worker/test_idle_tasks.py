import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.background_worker.idle_tasks import (
    _idle_task_handlers,
    _run_context_compaction,
    default_idle_callback,
    register_idle_task_handler,
)
from myrm_agent_harness.agent.background_worker.idle_worker import _idle_tasks, cancel_idle_task, schedule_idle_task
from myrm_agent_harness.agent.background_worker.registry import IdleTaskRecord, IdleTaskRegistry
from myrm_agent_harness.runtime.events.idle_events import IdleTaskProgressEvent
from myrm_agent_harness.runtime.maintenance.protocols import CapacityDenial, CapacityTicket


@pytest.fixture(autouse=True)
def clean_idle_tasks():
    # Clean up any scheduled tasks before and after each test
    _idle_tasks.clear()
    yield
    for task in _idle_tasks.values():
        if not task.done():
            task.cancel()
    _idle_tasks.clear()


@pytest.mark.asyncio
async def test_schedule_and_cancel_idle_task():
    session_id = "test_session_1"
    callback_executed = False

    async def mock_callback():
        nonlocal callback_executed
        callback_executed = True

    # Schedule task
    schedule_idle_task(session_id, mock_callback, delay_seconds=10)
    task = _idle_tasks[session_id]
    assert session_id in _idle_tasks

    # Cancel task
    cancel_idle_task(session_id)
    await asyncio.sleep(0.01)  # allow task state to update
    assert task.cancelled() or task.done()
    assert session_id not in _idle_tasks

    # Ensure callback was not executed
    assert not callback_executed


@pytest.mark.asyncio
async def test_schedule_idle_task_execution():
    session_id = "test_session_2"
    callback_executed = False

    async def mock_callback():
        nonlocal callback_executed
        callback_executed = True

    # Schedule task with very short delay
    schedule_idle_task(session_id, mock_callback, delay_seconds=0)

    # Yield control to allow background task to run
    await asyncio.sleep(0.1)

    assert callback_executed
    assert session_id not in _idle_tasks


@pytest.mark.asyncio
@patch("myrm_agent_harness.agent.background_worker.idle_tasks.get_maintenance_scheduler")
@patch("myrm_agent_harness.agent.background_worker.idle_tasks.get_memory_manager")
@patch("myrm_agent_harness.agent.background_worker.idle_tasks.CognitiveConsolidator")
async def test_default_idle_callback_success(mock_consolidator_class, mock_get_memory_manager, mock_get_scheduler):
    # Setup scheduler mock
    mock_scheduler = AsyncMock()
    mock_scheduler.report_outcome = MagicMock()
    mock_ticket = CapacityTicket(ticket_id="test_ticket", task_type="cognitive_consolidation")
    mock_scheduler.request_capacity.return_value = mock_ticket
    mock_get_scheduler.return_value = mock_scheduler

    # Setup EventBus mock
    mock_event_bus = MagicMock()
    with patch("myrm_agent_harness.agent.background_worker.idle_tasks.get_event_bus", return_value=mock_event_bus):
        # Setup memory manager and consolidator mock
        mock_memory_manager = MagicMock()
        mock_get_memory_manager.return_value = mock_memory_manager

        mock_consolidator_instance = AsyncMock()
        mock_consolidator_result = MagicMock()
        mock_consolidator_result.errors = []
        mock_consolidator_result.skipped = False
        mock_consolidator_result.to_dict.return_value = {"mock_data": True}
        mock_consolidator_instance.run_consolidation.return_value = mock_consolidator_result
        mock_consolidator_class.return_value = mock_consolidator_instance

        # Setup registry mock
        mock_registry = AsyncMock(spec=IdleTaskRegistry)
        mock_registry.acquire_next.return_value = IdleTaskRecord(
            id=1,
            session_id="sess1",
            task_type="cognitive_consolidation",
            payload={},
            status="running",
            created_at=0.0,
        )

        session_id = "test_session_3"

        # Mock asyncio.sleep to speed up tests
        with patch("asyncio.sleep", new_callable=AsyncMock):
            await default_idle_callback(session_id, mock_registry)

        # Assertions
        mock_scheduler.request_capacity.assert_called_once()
        mock_scheduler.release_capacity.assert_called_once_with(mock_ticket)
        mock_registry.acquire_next.assert_called_once_with(session_id)
        mock_registry.mark_completed.assert_called_once_with(1)

        # Verify events published
        published_events = [call.args[0] for call in mock_event_bus.publish.call_args_list]
        assert len(published_events) == 4
        assert all(isinstance(e, IdleTaskProgressEvent) for e in published_events)

        assert published_events[0].status == "working"
        assert published_events[0].progress_pct == 10

        assert published_events[1].status == "working"
        assert published_events[1].progress_pct == 50

        assert published_events[2].status == "completed"
        assert published_events[2].progress_pct == 100
        assert published_events[2].data == {"mock_data": True}

        assert published_events[3].status == "idle"


@pytest.mark.asyncio
@patch("myrm_agent_harness.agent.background_worker.idle_tasks.get_maintenance_scheduler")
async def test_default_idle_callback_denied(mock_get_scheduler):
    # Setup scheduler mock to deny capacity
    mock_scheduler = AsyncMock()
    mock_denial = CapacityDenial(reason="System overloaded")
    mock_scheduler.request_capacity.return_value = mock_denial
    mock_get_scheduler.return_value = mock_scheduler

    # Setup EventBus mock (should not be called for denied capacity)
    mock_event_bus = MagicMock()

    # Setup registry mock
    mock_registry = AsyncMock(spec=IdleTaskRegistry)
    mock_registry.acquire_next.return_value = IdleTaskRecord(
        id=1,
        session_id="sess1",
        task_type="cognitive_consolidation",
        payload={},
        status="running",
        created_at=0.0,
    )

    # We also need to mock _revert_task_to_pending
    with patch(
        "myrm_agent_harness.agent.background_worker.idle_tasks._revert_task_to_pending", new_callable=AsyncMock
    ) as mock_revert, patch(
        "myrm_agent_harness.agent.background_worker.idle_tasks.get_event_bus", return_value=mock_event_bus
    ):
        session_id = "test_session_4"
        await default_idle_callback(session_id, mock_registry)

        # Assertions
        mock_scheduler.request_capacity.assert_called_once()
        mock_event_bus.publish.assert_not_called()
        mock_revert.assert_called_once_with(mock_registry, 1)


@pytest.mark.asyncio
@patch("myrm_agent_harness.agent.background_worker.idle_tasks.get_maintenance_scheduler")
async def test_default_idle_callback_no_scheduler(mock_get_scheduler):
    # Setup scheduler mock to return None
    mock_get_scheduler.return_value = None

    # Setup registry mock
    mock_registry = AsyncMock(spec=IdleTaskRegistry)
    mock_registry.acquire_next.return_value = IdleTaskRecord(
        id=1,
        session_id="sess1",
        task_type="cognitive_consolidation",
        payload={},
        status="running",
        created_at=0.0,
    )

    session_id = "test_session_5"
    await default_idle_callback(session_id, mock_registry)

    # Should mark error immediately if no scheduler is present
    mock_registry.mark_error.assert_called_once_with(1)


# ---------------------------------------------------------------------------
# context_compaction handler tests
# ---------------------------------------------------------------------------


class TestRegisterIdleTaskHandler:
    """Tests for the handler registration mechanism."""

    def test_register_and_retrieve(self) -> None:
        handler = AsyncMock()
        register_idle_task_handler("_test_handler", handler)
        assert _idle_task_handlers["_test_handler"] is handler
        del _idle_task_handlers["_test_handler"]

    def test_overwrite_handler(self) -> None:
        h1 = AsyncMock()
        h2 = AsyncMock()
        register_idle_task_handler("_test_overwrite", h1)
        register_idle_task_handler("_test_overwrite", h2)
        assert _idle_task_handlers["_test_overwrite"] is h2
        del _idle_task_handlers["_test_overwrite"]


@pytest.mark.asyncio
class TestRunContextCompaction:
    """Tests for the _run_context_compaction function."""

    async def test_skip_when_no_chat_id(self) -> None:
        event_bus = MagicMock()
        task = IdleTaskRecord(
            id=10, session_id="s1", task_type="context_compaction",
            payload={}, status="running", created_at=0.0,
        )
        result = await _run_context_compaction("s1", task, event_bus)
        assert result["skipped"] is True
        assert result["reason"] == "no chat_id"

    async def test_compaction_success_no_preheat(self) -> None:
        event_bus = MagicMock()
        task = IdleTaskRecord(
            id=11, session_id="s2", task_type="context_compaction",
            payload={"chat_id": "chat_123"}, status="running", created_at=0.0,
        )
        compact_handler = AsyncMock(return_value={
            "compacted": True, "tokens_saved": 5000, "message_count": 20, "reason": "",
        })
        _idle_task_handlers["_context_compact_impl"] = compact_handler
        try:
            result = await _run_context_compaction("s2", task, event_bus)
            assert result["compacted"] is True
            assert result["preheated"] is False
            compact_handler.assert_awaited_once_with("chat_123", "s2")
            published = [c.args[0] for c in event_bus.publish.call_args_list]
            assert any(e.message == " Optimizing conversation context..." for e in published)
        finally:
            del _idle_task_handlers["_context_compact_impl"]

    async def test_compaction_not_needed(self) -> None:
        event_bus = MagicMock()
        task = IdleTaskRecord(
            id=12, session_id="s3", task_type="context_compaction",
            payload={"chat_id": "chat_short"}, status="running", created_at=0.0,
        )
        compact_handler = AsyncMock(return_value={
            "compacted": False, "tokens_saved": 0, "message_count": 5, "reason": "too_few_messages",
        })
        _idle_task_handlers["_context_compact_impl"] = compact_handler
        try:
            result = await _run_context_compaction("s3", task, event_bus)
            assert result["compacted"] is False
            assert result["preheated"] is False
        finally:
            del _idle_task_handlers["_context_compact_impl"]

    async def test_no_handler_registered(self) -> None:
        event_bus = MagicMock()
        task = IdleTaskRecord(
            id=13, session_id="s4", task_type="context_compaction",
            payload={"chat_id": "chat_456"}, status="running", created_at=0.0,
        )
        _idle_task_handlers.pop("_context_compact_impl", None)
        result = await _run_context_compaction("s4", task, event_bus)
        assert result["compacted"] is False

    async def test_handler_error_caught(self) -> None:
        event_bus = MagicMock()
        task = IdleTaskRecord(
            id=14, session_id="s5", task_type="context_compaction",
            payload={"chat_id": "chat_err"}, status="running", created_at=0.0,
        )
        compact_handler = AsyncMock(side_effect=RuntimeError("DB connection lost"))
        _idle_task_handlers["_context_compact_impl"] = compact_handler
        try:
            result = await _run_context_compaction("s5", task, event_bus)
            assert result["compacted"] is False
        finally:
            del _idle_task_handlers["_context_compact_impl"]

    async def test_preheat_triggered_when_llm_provided(self) -> None:
        event_bus = MagicMock()
        task = IdleTaskRecord(
            id=15, session_id="s6", task_type="context_compaction",
            payload={"chat_id": "chat_preheat"}, status="running", created_at=0.0,
        )
        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = MagicMock()
        mock_messages = [MagicMock()]
        compact_handler = AsyncMock(return_value={
            "compacted": True, "llm": mock_llm, "messages": mock_messages,
            "model_name": "anthropic/claude-3",
        })
        _idle_task_handlers["_context_compact_impl"] = compact_handler
        try:
            result = await _run_context_compaction("s6", task, event_bus)
            assert result["compacted"] is True
            assert result["preheated"] is True
            published = [c.args[0] for c in event_bus.publish.call_args_list]
            assert any(getattr(e, "message", "") == " Warming up cache..." for e in published)
        finally:
            del _idle_task_handlers["_context_compact_impl"]
