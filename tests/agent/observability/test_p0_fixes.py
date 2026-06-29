"""P0 optimization tests for tool call transparency enhancement.

Tests for:
- P0-1: Intelligent truncation in EventBus
- P0-2: Complete cancellation event lifecycle with cancel_reason
"""

import asyncio
import time

import pytest

from myrm_agent_harness.agent.observability.event_bus import EventBus
from myrm_agent_harness.agent.observability.tool_call_broadcaster import ToolCallBroadcaster
from myrm_agent_harness.agent.observability.types import ToolCallEventData


@pytest.mark.asyncio
async def test_p0_1_eventbus_truncation():
    """Test P0-1: EventBus truncates large result/error while preserving original for EventLogger."""
    EventBus._instance = None
    bus = await EventBus.get_instance()

    # Create event with large result
    large_result = "x" * 10000  # 10KB
    event = ToolCallEventData(
        tool_name="test_large_truncation",
        status="completed",
        start_time=time.time(),
        end_time=time.time(),
        duration_ms=100,
        result=large_result,
    )

    # Collect published events
    published_events = []

    async def collector(event: ToolCallEventData) -> None:
        published_events.append(event)

    bus.subscribe(collector)

    try:
        # Publish and wait for processing
        await bus.publish(event)
        await asyncio.sleep(0.5)

        # Find our specific event
        matching = [e for e in published_events if e.tool_name == "test_large_truncation"]
        assert len(matching) >= 1
        published_event = matching[0]

        assert published_event.status == "completed"

        # Result should be truncated
        assert isinstance(published_event.result, str)
        assert len(published_event.result) < len(large_result)
        assert "Truncated" in published_event.result or len(published_event.result) <= 1044  # 1024 + marker overhead

        # Original event remains unchanged (immutable dataclass)
        assert event.result == large_result
    finally:
        bus.unsubscribe(collector)


@pytest.mark.asyncio
async def test_p0_2_cancel_reason():
    """Test P0-2: Cancellation events include cancel_reason."""
    broadcaster = ToolCallBroadcaster(event_logger=None)

    # Test different cancel reasons
    cancel_reasons = ["user_cancelled", "timeout", "session_ended", "unknown"]

    for reason in cancel_reasons:
        result = await broadcaster.on_post_tool_use_cancelled(
            "post_tool_use_cancelled",
            {
                "tool_name": "test_tool",
                "tool_call_id": "test_id_" + reason,
                "cancel_reason": reason,
            },
        )

        assert result.success is True
        assert result.hook_type == "tool_call_broadcaster"


@pytest.mark.asyncio
async def test_p0_2_cancel_reason_in_event_data():
    """Test P0-2: ToolCallEventData includes and serializes cancel_reason."""
    event = ToolCallEventData(
        tool_name="test_tool",
        status="cancelled",
        start_time=time.time(),
        end_time=time.time(),
        duration_ms=100,
        error="Tool execution was cancelled",
        cancel_reason="user_cancelled",
    )

    # Verify field exists
    assert event.cancel_reason == "user_cancelled"

    # Verify serialization
    event_dict = event.to_dict()
    assert "cancel_reason" in event_dict
    assert event_dict["cancel_reason"] == "user_cancelled"

    # Verify JSON serialization
    event_json = event.to_json()
    assert "user_cancelled" in event_json


def test_p0_1_truncation_logic():
    """Test P0-1: Truncation logic for small results (unit test)."""
    from myrm_agent_harness.agent.observability.types import _truncate_for_event

    # Small result should not be truncated
    small_result = "small result"
    truncated = _truncate_for_event(small_result, max_bytes=1024)
    assert truncated == small_result

    # Large result should be truncated
    large_result = "x" * 10000
    truncated = _truncate_for_event(large_result, max_bytes=1024)
    assert isinstance(truncated, str)
    assert len(truncated) < len(large_result)
    assert "Truncated" in truncated or len(truncated) <= 1044
