"""Verify error_category and error_hint propagate through SSE event_handlers.

Tests the data flow: ToolMessage.additional_kwargs → SSE event dict,
ensuring StrEnum values serialize correctly as plain strings for
frontend i18n lookup.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import ToolMessage

from myrm_agent_harness.agent.errors.tool_error_category import ToolErrorCategory
from myrm_agent_harness.agent.streaming.event_handlers import (
    _emit_source_events,
    _handle_tool_result,
    process_updates_chunk,
)
from myrm_agent_harness.agent.streaming.source_tracker import SourceTracker
from myrm_agent_harness.agent.streaming.types import AgentEventType
from myrm_agent_harness.agent.types import AgentRunStatistics


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
    # Error steps carry the tool_call_id so trace_builder can pair them with
    # the lifecycle tool_failure event (no duplicate trace records).
    assert step_event["tool_call_id"] == "call_1"


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
    # Without a category, tool errors default to HARNESS_TOOL.
    assert events[0]["fault_side"] == "harness_tool"


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
    # User-triggered guard categories (estop) attribute to OWNER, not the tool.
    assert events[0]["fault_side"] == "owner"


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
    # Content/guardrail blocks are user-input triggers → OWNER.
    assert events[0]["fault_side"] == "owner"


@pytest.mark.asyncio
async def test_interrupt_plan_confirm_emits_waiting_status() -> None:
    """A ``plan_confirm`` interrupt surfaces as a waiting status for the plan UI."""
    from langgraph.types import Interrupt

    payload = {
        "action_type": "plan_confirm",
        "plan_items": ["step one", "step two"],
        "total_items": 2,
        "goal": "ship it",
    }
    events: list[dict] = []
    async for event in process_updates_chunk(
        {"__interrupt__": (Interrupt(value=payload),)},
        AgentRunStatistics(),
        "msg_plan",
    ):
        events.append(event)

    assert len(events) == 1
    assert events[0]["type"] == AgentEventType.STATUS.value
    assert events[0]["data"]["phase"] == "plan_confirm"
    assert events[0]["data"]["status"] == "waiting"
    assert events[0]["data"]["plan_items"] == ["step one", "step two"]
    assert events[0]["data"]["goal"] == "ship it"
    assert events[0]["messageId"] == "msg_plan"


@pytest.mark.asyncio
async def test_interrupt_tool_approval_request_emits_payload() -> None:
    """A non-plan interrupt surfaces the raw approval payload for the frontend."""
    from langgraph.types import Interrupt

    payload = {"actionRequests": [{"action": "browser_ask_human"}, {"action": "file_write"}]}
    events: list[dict] = []
    async for event in process_updates_chunk(
        {"__interrupt__": (Interrupt(value=payload),)},
        AgentRunStatistics(),
        "msg_approval",
    ):
        events.append(event)

    assert len(events) == 1
    assert events[0]["type"] == AgentEventType.TOOL_APPROVAL_REQUEST.value
    assert events[0]["data"] == payload
    assert events[0]["messageId"] == "msg_approval"


@pytest.mark.asyncio
async def test_interrupt_without_action_requests_labels_unknown() -> None:
    """An interrupt carrying no parsable actionRequests still emits an approval request."""
    from langgraph.types import Interrupt

    events: list[dict] = []
    async for event in process_updates_chunk(
        {"__interrupt__": (Interrupt(value={"foo": "bar"}),)},
        AgentRunStatistics(),
        "msg_unknown",
    ):
        events.append(event)

    assert len(events) == 1
    assert events[0]["type"] == AgentEventType.TOOL_APPROVAL_REQUEST.value
    assert events[0]["data"] == {"foo": "bar"}


@pytest.mark.asyncio
async def test_source_events_emit_steps_and_sources() -> None:
    """Newly tracked sources emit both the progress step and the citation event."""
    tracker = SourceTracker()
    metadata = {"sources": [{"url": "https://example.com/a", "title": "A"}]}

    events: list[dict] = []
    async for event in _emit_source_events(metadata, "msg_src", tracker):
        events.append(event)

    assert [event["type"] for event in events] == [
        AgentEventType.TASKS_STEPS.value,
        AgentEventType.SOURCES.value,
    ]
    assert events[0]["step_key"] == "reviewing_sources"
    assert events[0]["count"] == 1
    assert events[0]["messageId"] == "msg_src"


@pytest.mark.asyncio
async def test_source_events_silent_when_no_new_sources() -> None:
    """Duplicates must not re-emit the step or the citation event."""
    tracker = SourceTracker()
    metadata = {"sources": [{"url": "https://example.com/a", "title": "A"}]}

    async for _ in _emit_source_events(metadata, "msg_first", tracker):
        pass

    repeat: list[dict] = []
    async for event in _emit_source_events(metadata, "msg_second", tracker):
        repeat.append(event)

    assert repeat == []
