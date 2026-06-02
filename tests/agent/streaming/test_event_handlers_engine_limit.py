import pytest
from langchain_core.messages import ToolMessage

from myrm_agent_harness.agent.streaming.event_handlers import _handle_tool_result
from myrm_agent_harness.agent.streaming.types import AgentEventType


@pytest.mark.asyncio
async def test_handle_tool_result_engine_limit_tool_calls():
    """Test that ToolCallLimitMiddleware errors emit ENGINE_LIMIT_REACHED."""
    msg = ToolMessage(
        content="Tool call limit exceeded. Do not call 'bash_tool' again.",
        name="bash_tool",
        tool_call_id="call_1",
        status="error",
    )

    events = []
    async for event in _handle_tool_result(msg, "test_msg_id", None):
        events.append(event)

    # Should emit TASKS_STEPS error and ENGINE_LIMIT_REACHED
    assert len(events) == 2

    assert events[0]["type"] == AgentEventType.TASKS_STEPS.value
    assert events[0]["status"] == "error"

    assert events[1]["type"] == AgentEventType.ENGINE_LIMIT_REACHED.value
    assert events[1]["data"]["limit_type"] == "max_tool_calls"
    assert events[1]["data"]["tool_name"] == "bash_tool"


@pytest.mark.asyncio
async def test_handle_tool_result_engine_limit_replan():
    """Test that ReplanMiddleware errors emit ENGINE_LIMIT_REACHED."""
    msg = ToolMessage(
        content="ToolExecutionError: Some error\n\nEngine limit reached: max_replan_attempts exceeded (3).",
        name="some_tool",
        tool_call_id="call_2",
        status="error",
    )

    events = []
    async for event in _handle_tool_result(msg, "test_msg_id", None):
        events.append(event)

    assert len(events) == 2

    assert events[0]["type"] == AgentEventType.TASKS_STEPS.value
    assert events[0]["status"] == "error"

    assert events[1]["type"] == AgentEventType.ENGINE_LIMIT_REACHED.value
    assert events[1]["data"]["limit_type"] == "max_replan_attempts"
    assert events[1]["data"]["tool_name"] == "some_tool"
