from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.background_worker.idle_tasks import default_idle_callback
from myrm_agent_harness.runtime.events.idle_events import IdleTaskProgressEvent


@dataclass
class _FakeTask:
    id: int
    task_type: str
    payload: dict[str, Any]

@pytest.fixture
def mock_registry():
    registry = AsyncMock()
    registry.acquire_next = AsyncMock()
    registry.mark_completed = AsyncMock()
    registry.mark_error = AsyncMock()
    return registry

@pytest.fixture
def mock_scheduler():
    scheduler = AsyncMock()

    @dataclass
    class _FakeTicket:
        ticket_id: str
        task_type: str

    scheduler.request_capacity = AsyncMock(return_value=_FakeTicket("t1", "cognitive_derivation"))
    scheduler.release_capacity = AsyncMock()
    scheduler.report_outcome = MagicMock()
    return scheduler

@pytest.fixture
def mock_event_bus():
    bus = MagicMock()
    bus.publish = MagicMock()
    return bus

@pytest.fixture
def mock_memory_manager():
    return MagicMock()

@pytest.mark.asyncio
@patch("myrm_agent_harness.agent.background_worker.idle_tasks.get_maintenance_scheduler")
@patch("myrm_agent_harness.agent.background_worker.idle_tasks.get_event_bus")
@patch("myrm_agent_harness.agent.background_worker.idle_tasks.get_memory_manager")
@patch("myrm_agent_harness.toolkits.memory.cognitive.deriver.CognitiveDeriver")
@patch("asyncio.sleep", new_callable=AsyncMock)
async def test_idle_tasks_sse_noise_reduction_disruptive(
    mock_sleep, mock_deriver_cls, mock_get_memory, mock_get_bus, mock_get_scheduler,
    mock_registry, mock_scheduler, mock_event_bus, mock_memory_manager
):
    mock_registry.acquire_next.return_value = _FakeTask(
        id=1, task_type="cognitive_derivation", payload={"chat_id": "c1", "messages": [{"role": "user", "content": "test"}]}
    )
    mock_get_scheduler.return_value = mock_scheduler
    mock_get_bus.return_value = mock_event_bus
    mock_get_memory.return_value = mock_memory_manager

    mock_deriver_instance = AsyncMock()
    mock_deriver_instance.run_derivation.return_value = {
        "success": True,
        "extracted_count": 1,
        "has_disruptive_change": True, # Disruptive change
    }
    mock_deriver_cls.return_value = mock_deriver_instance

    await default_idle_callback("sess1", mock_registry)

    # Check published events
    # 1. Started
    # 2. Working (derivation)
    # 3. Notification/Completed (from derivation)
    # 4. Completed
    # 5. Idle (finally)
    publish_calls = mock_event_bus.publish.call_args_list

    # Find the derivation result event
    derivation_event = next(
        (call[0][0] for call in publish_calls
         if isinstance(call[0][0], IdleTaskProgressEvent) and
         call[0][0].data and
         call[0][0].data.get("type") == "cognitive_derivation"),
        None
    )

    assert derivation_event is not None
    assert derivation_event.status == "notification" # Should be notification for disruptive
    assert "认知已更新" in derivation_event.message
    assert derivation_event.data["urgency"] == "notify"

@pytest.mark.asyncio
@patch("myrm_agent_harness.agent.background_worker.idle_tasks.get_maintenance_scheduler")
@patch("myrm_agent_harness.agent.background_worker.idle_tasks.get_event_bus")
@patch("myrm_agent_harness.agent.background_worker.idle_tasks.get_memory_manager")
@patch("myrm_agent_harness.toolkits.memory.cognitive.deriver.CognitiveDeriver")
@patch("asyncio.sleep", new_callable=AsyncMock)
async def test_idle_tasks_sse_noise_reduction_silent(
    mock_sleep, mock_deriver_cls, mock_get_memory, mock_get_bus, mock_get_scheduler,
    mock_registry, mock_scheduler, mock_event_bus, mock_memory_manager
):
    mock_registry.acquire_next.return_value = _FakeTask(
        id=1, task_type="cognitive_derivation", payload={"chat_id": "c1", "messages": [{"role": "user", "content": "test"}]}
    )
    mock_get_scheduler.return_value = mock_scheduler
    mock_get_bus.return_value = mock_event_bus
    mock_get_memory.return_value = mock_memory_manager

    mock_deriver_instance = AsyncMock()
    mock_deriver_instance.run_derivation.return_value = {
        "success": True,
        "extracted_count": 1,
        "has_disruptive_change": False, # Non-disruptive
    }
    mock_deriver_cls.return_value = mock_deriver_instance

    await default_idle_callback("sess1", mock_registry)

    publish_calls = mock_event_bus.publish.call_args_list

    derivation_event = next(
        (call[0][0] for call in publish_calls
         if isinstance(call[0][0], IdleTaskProgressEvent) and
         call[0][0].data and
         call[0][0].data.get("type") == "cognitive_derivation"),
        None
    )

    assert derivation_event is not None
    assert derivation_event.status == "completed" # Should be silent completion
    assert derivation_event.message == ""
    assert derivation_event.data["urgency"] == "silent"
