"""Unit tests for __interrupt__ event handling in event_handlers."""

import pytest
from langchain_core.messages import AIMessage
from langgraph.types import Interrupt

from myrm_agent_harness.agent.streaming.event_handlers import process_updates_chunk
from myrm_agent_harness.agent.streaming.types import AgentEventType
from myrm_agent_harness.agent.types import AgentRunStatistics


@pytest.mark.asyncio
async def test_interrupt_node_single_interrupt():
    """Test handling single Interrupt object in __interrupt__ node."""
    interrupt_payload = {
        "type": "tool_approval",
        "tool_name": "bash_code_execute_tool",
        "tool_input": {"code": "ls"},
        "reason": "Requires approval",
        "permission_type": "code_interpreter",
        "session_key": "test_session",
        "display_mode": "approval",
    }

    data = {"__interrupt__": (Interrupt(value=interrupt_payload),)}

    stats = AgentRunStatistics()
    events = []

    async for event in process_updates_chunk(data, stats, "msg_001"):
        events.append(event)

    assert len(events) == 1
    assert events[0]["type"] == AgentEventType.TOOL_APPROVAL_REQUEST.value
    assert events[0]["data"] == interrupt_payload
    assert events[0]["messageId"] == "msg_001"


@pytest.mark.asyncio
async def test_interrupt_node_multiple_interrupts():
    """Test handling multiple Interrupt objects in __interrupt__ node."""
    payload1 = {
        "type": "tool_approval",
        "tool_name": "tool1",
        "tool_input": {},
        "reason": "",
    }

    payload2 = {
        "type": "tool_approval",
        "tool_name": "tool2",
        "tool_input": {},
        "reason": "",
    }

    data = {"__interrupt__": (Interrupt(value=payload1), Interrupt(value=payload2))}

    stats = AgentRunStatistics()
    events = []

    async for event in process_updates_chunk(data, stats, "msg_002"):
        events.append(event)

    assert len(events) == 2
    assert all(e["type"] == AgentEventType.TOOL_APPROVAL_REQUEST.value for e in events)
    assert events[0]["data"] == payload1
    assert events[1]["data"] == payload2


@pytest.mark.asyncio
async def test_interrupt_node_empty_tuple():
    """Test handling empty tuple in __interrupt__ node."""
    data = {"__interrupt__": ()}

    stats = AgentRunStatistics()
    events = []

    async for event in process_updates_chunk(data, stats, "msg_003"):
        events.append(event)

    assert len(events) == 0


@pytest.mark.asyncio
async def test_interrupt_node_invalid_type():
    """Test handling non-Interrupt objects in __interrupt__ node."""
    data = {"__interrupt__": ("not_an_interrupt")}

    stats = AgentRunStatistics()
    events = []

    async for event in process_updates_chunk(data, stats, "msg_004"):
        events.append(event)

    # Should not yield any events for invalid types
    assert len(events) == 0


@pytest.mark.asyncio
async def test_interrupt_preserves_other_nodes():
    """Test that __interrupt__ handling doesn't affect other node processing."""
    interrupt_payload = {
        "type": "tool_approval",
        "tool_name": "test_tool",
        "tool_input": {},
        "reason": "",
    }

    data = {
            "__interrupt__": (Interrupt(value=interrupt_payload),),
        "model": {"messages": [AIMessage(content="test")]},
    }

    stats = AgentRunStatistics()
    events = []

    async for event in process_updates_chunk(data, stats, "msg_005"):
        events.append(event)

    # Should have both interrupt event and model event processing
    approval_events = [e for e in events if e.get("type") == AgentEventType.TOOL_APPROVAL_REQUEST.value]
    assert len(approval_events) == 1
