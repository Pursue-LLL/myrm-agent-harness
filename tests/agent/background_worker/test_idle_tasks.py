import asyncio
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.language_models import BaseChatModel

from myrm_agent_harness.agent.background_worker import idle_tasks
from myrm_agent_harness.agent.background_worker.idle_tasks import (
    _idle_task_handlers,
    _run_context_compaction,
    default_idle_callback,
    register_context_compaction_handler,
    register_idle_task_handler,
)
from myrm_agent_harness.agent.background_worker.idle_worker import _idle_tasks, cancel_idle_task, schedule_idle_task
from myrm_agent_harness.agent.background_worker.registry import IdleTaskRecord, IdleTaskRegistry
from myrm_agent_harness.runtime.events.idle_events import IdleTaskProgressEvent
from myrm_agent_harness.runtime.maintenance.protocols import CapacityDenial, CapacityTicket


@pytest.fixture(autouse=True)
def reset_context_compaction_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(idle_tasks, "_context_compaction_handler", None)


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

        # Presentation text belongs to the UI layer; events carry structure only.
        assert not any(hasattr(e, "message") for e in published_events)


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

    with patch("myrm_agent_harness.agent.background_worker.idle_tasks.get_event_bus", return_value=mock_event_bus):
        ran = await default_idle_callback("test_session_4", mock_registry)

    assert ran is False
    mock_scheduler.request_capacity.assert_called_once()
    mock_event_bus.publish.assert_not_called()
    mock_registry.requeue.assert_awaited_once_with(1)


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

    ran = await default_idle_callback("test_session_5", mock_registry)

    # Without a scheduler nothing may run, and the task stays available for a later window
    assert ran is False
    mock_registry.requeue.assert_awaited_once_with(1)
    mock_registry.mark_error.assert_not_called()


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
            id=10,
            session_id="s1",
            task_type="context_compaction",
            payload={},
            status="running",
            created_at=0.0,
        )
        result = await _run_context_compaction("s1", task, event_bus)
        assert result["skipped"] is True
        assert result["reason"] == "no chat_id"

    async def test_compaction_success_no_preheat(self) -> None:
        event_bus = MagicMock()
        task = IdleTaskRecord(
            id=11,
            session_id="s2",
            task_type="context_compaction",
            payload={"chat_id": "chat_123"},
            status="running",
            created_at=0.0,
        )
        compact_handler = AsyncMock(
            return_value={
                "compacted": True,
                "tokens_saved": 5000,
                "message_count": 20,
                "reason": "",
            }
        )
        register_context_compaction_handler(compact_handler)
        result = await _run_context_compaction("s2", task, event_bus)
        assert result == {"compacted": True, "chat_id": "chat_123"}
        compact_handler.assert_awaited_once_with("chat_123", "s2")
        published = [c.args[0] for c in event_bus.publish.call_args_list]
        assert [(e.status, e.task_name) for e in published] == [("working", "context_compaction")]

    async def test_compaction_not_needed(self) -> None:
        event_bus = MagicMock()
        task = IdleTaskRecord(
            id=12,
            session_id="s3",
            task_type="context_compaction",
            payload={"chat_id": "chat_short"},
            status="running",
            created_at=0.0,
        )
        compact_handler = AsyncMock(
            return_value={
                "compacted": False,
                "tokens_saved": 0,
                "message_count": 5,
                "reason": "too_few_messages",
            }
        )
        register_context_compaction_handler(compact_handler)
        result = await _run_context_compaction("s3", task, event_bus)
        assert result == {"compacted": False, "chat_id": "chat_short"}

    async def test_no_handler_registered(self) -> None:
        event_bus = MagicMock()
        task = IdleTaskRecord(
            id=13,
            session_id="s4",
            task_type="context_compaction",
            payload={"chat_id": "chat_456"},
            status="running",
            created_at=0.0,
        )
        result = await _run_context_compaction("s4", task, event_bus)
        assert result["compacted"] is False

    async def test_handler_error_caught(self) -> None:
        event_bus = MagicMock()
        task = IdleTaskRecord(
            id=14,
            session_id="s5",
            task_type="context_compaction",
            payload={"chat_id": "chat_err"},
            status="running",
            created_at=0.0,
        )
        compact_handler = AsyncMock(side_effect=RuntimeError("DB connection lost"))
        register_context_compaction_handler(compact_handler)
        result = await _run_context_compaction("s5", task, event_bus)
        assert result["compacted"] is False

    async def test_compaction_never_preheats_prefix_cache(self) -> None:
        """Idle compaction runs minutes after the provider cache TTL, so it must not re-warm it."""
        event_bus = MagicMock()
        task = IdleTaskRecord(
            id=15,
            session_id="s6",
            task_type="context_compaction",
            payload={"chat_id": "chat_preheat"},
            status="running",
            created_at=0.0,
        )
        compact_handler = AsyncMock(
            return_value={
                "compacted": True,
                "llm": AsyncMock(),
                "messages": [MagicMock()],
                "model_name": "anthropic/claude-3",
            }
        )
        register_context_compaction_handler(compact_handler)
        with patch(
            "myrm_agent_harness.agent.context_management.preheat.preheat_prefix_cache",
            new_callable=AsyncMock,
        ) as mock_preheat:
            result = await _run_context_compaction("s6", task, event_bus)
        assert result == {"compacted": True, "chat_id": "chat_preheat"}
        mock_preheat.assert_not_awaited()


@pytest.mark.asyncio
async def test_cognitive_subsumption_passes_consolidation_llm_by_signature() -> None:
    """The idle handler must call find_subsumed_memories with its real ``llm`` parameter."""
    registry = AsyncMock(spec=IdleTaskRegistry)
    registry.acquire_next.return_value = IdleTaskRecord(
        id=30,
        session_id="global",
        task_type="cognitive_subsumption",
        payload={"new_knowledge": "evolved skill body", "skill_id": "skill_1"},
        status="running",
        created_at=0.0,
    )
    consolidation_llm = MagicMock(spec=BaseChatModel)

    with (
        patch("myrm_agent_harness.agent.background_worker.idle_tasks.get_maintenance_scheduler") as mock_sched,
        patch("myrm_agent_harness.agent.background_worker.idle_tasks.get_event_bus") as mock_bus,
        patch("myrm_agent_harness.agent.background_worker.idle_tasks.get_memory_manager") as mock_mm,
        patch(
            "myrm_agent_harness.toolkits.memory.strategies.subsumption.find_subsumed_memories",
            autospec=True,
            return_value=[],
        ) as mock_find,
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        scheduler = AsyncMock()
        scheduler.report_outcome = MagicMock()
        scheduler.request_capacity.return_value = CapacityTicket(ticket_id="t_sub", task_type="cognitive_subsumption")
        mock_sched.return_value = scheduler
        mock_bus.return_value = MagicMock()
        manager = MagicMock()
        manager._consolidation_llm = consolidation_llm
        mock_mm.return_value = manager

        await default_idle_callback("global", registry)

    mock_find.assert_awaited_once()
    assert mock_find.await_args.kwargs["llm"] is consolidation_llm
    registry.mark_completed.assert_awaited_once()
    registry.mark_error.assert_not_awaited()


async def _run_task_collecting_events(
    task: IdleTaskRecord,
    manager: MagicMock,
    extra_patches: tuple[object, ...] = (),
) -> list[IdleTaskProgressEvent]:
    """Run one idle task through ``default_idle_callback`` and return every published event."""
    registry = AsyncMock(spec=IdleTaskRegistry)
    registry.acquire_next.return_value = task
    scheduler = AsyncMock()
    scheduler.report_outcome = MagicMock()
    scheduler.request_capacity.return_value = CapacityTicket(ticket_id="t", task_type=task.task_type)
    event_bus = MagicMock()

    with (
        patch(
            "myrm_agent_harness.agent.background_worker.idle_tasks.get_maintenance_scheduler", return_value=scheduler
        ),
        patch("myrm_agent_harness.agent.background_worker.idle_tasks.get_event_bus", return_value=event_bus),
        patch("myrm_agent_harness.agent.background_worker.idle_tasks.get_memory_manager", return_value=manager),
        patch("asyncio.sleep", new_callable=AsyncMock),
        ExitStack() as stack,
    ):
        for extra in extra_patches:
            stack.enter_context(extra)
        await default_idle_callback(task.session_id, registry)

    return [c.args[0] for c in event_bus.publish.call_args_list]


@pytest.mark.asyncio
async def test_cognitive_subsumption_notification_carries_count_and_ids_not_text() -> None:
    task = IdleTaskRecord(
        id=31,
        session_id="global",
        task_type="cognitive_subsumption",
        payload={"new_knowledge": "evolved skill body"},
        status="running",
        created_at=0.0,
    )
    manager = MagicMock()
    manager._consolidation_llm = MagicMock(spec=BaseChatModel)

    events = await _run_task_collecting_events(
        task,
        manager,
        (
            patch(
                "myrm_agent_harness.toolkits.memory.strategies.subsumption.find_subsumed_memories",
                autospec=True,
                return_value=["m1", "m2"],
            ),
            patch(
                "myrm_agent_harness.toolkits.memory.strategies.subsumption.apply_subsumption",
                autospec=True,
                return_value=2,
            ),
        ),
    )

    notification = next(e for e in events if e.status == "notification")
    assert notification.task_name == "cognitive_subsumption"
    assert notification.data is not None
    assert notification.data["count"] == 2
    assert notification.data["subsumed_ids"] == ["m1", "m2"]
    assert not any(hasattr(e, "message") for e in events)
