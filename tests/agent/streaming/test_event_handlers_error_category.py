"""Verify error_category and error_hint propagate through SSE event_handlers.

Tests the data flow: ToolMessage.additional_kwargs → SSE event dict,
ensuring StrEnum values serialize correctly as plain strings for
frontend i18n lookup.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import ToolMessage

from myrm_agent_harness.agent.errors.tool_error_category import ToolErrorCategory
from myrm_agent_harness.agent.streaming.event_handlers import _handle_tool_result
from myrm_agent_harness.agent.streaming.types import AgentEventType


async def _collect_events(msg: ToolMessage) -> list[dict]:
    events: list[dict] = []
    async for event in _handle_tool_result(msg, "msg_123", None):
        events.append(event)
    return events


@pytest.mark.asyncio
async def test_str_enum_category_propagates() -> None:
    """ToolErrorCategory StrEnum value should appear as plain string in SSE."""
    msg = ToolMessage(
        content="ToolExecutionError: Permission denied",
        name="bash_code_execute_tool",
        tool_call_id="call_1",
        status="error",
        additional_kwargs={
            "error_category": ToolErrorCategory.PERMISSION_DENIED,
            "error_hint": "Try 'chmod +x' or run in sandbox",
        },
    )
    events = await _collect_events(msg)

    assert len(events) >= 1
    step_event = events[0]
    assert step_event["type"] == AgentEventType.TASKS_STEPS.value
    assert step_event["status"] == "error"
    assert step_event["fault_side"] == "harness_tool"
    assert step_event["error_category"] == "permission_denied"
    assert isinstance(step_event["error_category"], str)
    assert step_event["error_hint"] == "Try 'chmod +x' or run in sandbox"


@pytest.mark.asyncio
async def test_raw_string_category_propagates() -> None:
    """Legacy raw string error_category still works (backward compat)."""
    msg = ToolMessage(
        content="ToolExecutionError: Timeout",
        name="bash_code_execute_tool",
        tool_call_id="call_2",
        status="error",
        additional_kwargs={"error_category": "timeout"},
    )
    events = await _collect_events(msg)

    assert events[0]["error_category"] == "timeout"


@pytest.mark.asyncio
async def test_no_category_omits_field() -> None:
    """When no error_category, SSE event should NOT include the field."""
    msg = ToolMessage(
        content="ToolExecutionError: Something failed",
        name="bash_code_execute_tool",
        tool_call_id="call_3",
        status="error",
    )
    events = await _collect_events(msg)

    assert "error_category" not in events[0]
    assert "error_hint" not in events[0]


@pytest.mark.asyncio
async def test_guards_category_propagates() -> None:
    """Guard layer categories (StrEnum) propagate correctly."""
    msg = ToolMessage(
        content="ToolExecutionError: Emergency stop activated",
        name="file_write_tool",
        tool_call_id="call_4",
        status="error",
        additional_kwargs={
            "error_category": ToolErrorCategory.ESTOP,
        },
    )
    events = await _collect_events(msg)

    assert events[0]["error_category"] == "estop"
    assert "error_hint" not in events[0]


@pytest.mark.asyncio
async def test_myrm_tools_guardrail_blocked_propagates() -> None:
    """bash myrm_tools preflight errors should surface guardrail_blocked in SSE."""
    msg = ToolMessage(
        content="ToolExecutionError: Command blocked: import myrm_tools",
        name="bash_code_execute_tool",
        tool_call_id="call_guardrail",
        status="error",
        additional_kwargs={
            "error_category": ToolErrorCategory.GUARDRAIL_BLOCKED,
            "error_hint": "Do not use myrm_tools in bash. For MCP scripts use skills.*/tools.* imports.",
        },
    )
    events = await _collect_events(msg)

    assert events[0]["error_category"] == "guardrail_blocked"
    assert "myrm_tools" in events[0]["error_hint"]
