"""Unit tests for protocol-safe cut point selector and tool pairing invariant guard."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from myrm_agent_harness.runtime.context.cut_point_selector import (
    CutPointAlignmentStrategy,
    ToolPairingViolationType,
    find_protocol_safe_cut_point,
    is_permitted_cut_point,
    repair_tool_pairing_invariants,
    validate_tool_pairing_invariants,
)


def test_is_permitted_cut_point_boundaries_and_types() -> None:
    """Validate whitelist permissions at boundaries and on specific message types."""
    messages = [
        SystemMessage(content="System prompt"),
        HumanMessage(content="User task"),
        AIMessage(
            content="Tool invocation",
            tool_calls=[{"name": "exec", "args": {"cmd": "ls"}, "id": "call_1"}],
        ),
        ToolMessage(content="file1.txt", tool_call_id="call_1"),
        AIMessage(content="Final response without tools"),
    ]

    # Extreme boundaries are always permitted
    assert is_permitted_cut_point(messages, 0)
    assert is_permitted_cut_point(messages, len(messages))
    assert is_permitted_cut_point(messages, -1)
    assert is_permitted_cut_point(messages, 999)

    # Cut index 1 is HumanMessage: permitted
    assert is_permitted_cut_point(messages, 1)

    # Cut index 3 is ToolMessage: strictly forbidden
    assert not is_permitted_cut_point(messages, 3)

    # Cut index 4 is AIMessage without tools following ToolMessage: permitted
    assert is_permitted_cut_point(messages, 4)


def test_find_protocol_safe_cut_point_single_tool_pull_and_push() -> None:
    """Verify single tool group alignment: pull_backward vs push_forward."""
    messages = [
        HumanMessage(content="Initial prompt"),
        AIMessage(
            content="Calling tool",
            tool_calls=[{"name": "fetch", "args": {}, "id": "c1"}],
        ),
        ToolMessage(content="Result", tool_call_id="c1"),
        HumanMessage(content="Next prompt"),
    ]

    # Target index 2 lands on ToolMessage
    pulled = find_protocol_safe_cut_point(messages, 2, CutPointAlignmentStrategy.PULL_BACKWARD)
    assert pulled == 1  # Shifts back to AIMessage

    pushed = find_protocol_safe_cut_point(messages, 2, CutPointAlignmentStrategy.PUSH_FORWARD)
    assert pushed == 3  # Shifts forward past ToolMessage


def test_find_protocol_safe_cut_point_parallel_tool_calls() -> None:
    """Verify multi-tool concurrent calls: cut point mid-group is atomic aligned."""
    messages = [
        HumanMessage(content="Run 3 tools"),
        AIMessage(
            content="Invoking tools in parallel",
            tool_calls=[
                {"name": "t1", "args": {}, "id": "c1"},
                {"name": "t2", "args": {}, "id": "c2"},
                {"name": "t3", "args": {}, "id": "c3"},
            ],
        ),
        ToolMessage(content="Res 1", tool_call_id="c1"),
        ToolMessage(content="Res 2", tool_call_id="c2"),
        ToolMessage(content="Res 3", tool_call_id="c3"),
        HumanMessage(content="Next user instruction"),
    ]

    # Target index 3 lands on the second tool result (c2)
    pulled = find_protocol_safe_cut_point(messages, 3, CutPointAlignmentStrategy.PULL_BACKWARD)
    assert pulled == 1  # Pulls whole parallel call back to the AIMessage

    pushed = find_protocol_safe_cut_point(messages, 3, CutPointAlignmentStrategy.PUSH_FORWARD)
    assert pushed == 5  # Pushes past all 3 tool results to HumanMessage


def test_validate_tool_pairing_invariants_valid_flow() -> None:
    """A structurally sound message sequence passes validation."""
    messages = [
        SystemMessage(content="System"),
        HumanMessage(content="Hello"),
        AIMessage(content="Greeting"),
        HumanMessage(content="Calculate 2+2"),
        AIMessage(
            content="Calling math",
            tool_calls=[{"name": "calc", "args": {"expr": "2+2"}, "id": "calc_1"}],
        ),
        ToolMessage(content="4", tool_call_id="calc_1"),
        AIMessage(content="The result is 4"),
    ]
    result = validate_tool_pairing_invariants(messages)
    assert result.is_valid
    assert len(result.violations) == 0


def test_validate_tool_pairing_invariants_detects_violations() -> None:
    """Detect orphan tool messages and unclosed tool calls."""
    # 1. Orphan tool message
    orphan_list = [
        HumanMessage(content="Where did this come from?"),
        ToolMessage(content="Random tool output", tool_call_id="unknown_id"),
    ]
    res1 = validate_tool_pairing_invariants(orphan_list)
    assert not res1.is_valid
    assert len(res1.violations) == 1
    assert res1.violations[0].violation_type == ToolPairingViolationType.ORPHAN_TOOL_RESULT

    # 2. Unclosed tool call
    unclosed_list = [
        HumanMessage(content="Do task"),
        AIMessage(
            content="Called tool",
            tool_calls=[{"name": "t1", "args": {}, "id": "c1"}, {"name": "t2", "args": {}, "id": "c2"}],
        ),
        ToolMessage(content="Result 1", tool_call_id="c1"),
        HumanMessage(content="Premature human message without c2 response"),
    ]
    res2 = validate_tool_pairing_invariants(unclosed_list)
    assert not res2.is_valid
    assert len(res2.violations) == 1
    assert res2.violations[0].violation_type == ToolPairingViolationType.UNCLOSED_TOOL_CALL
    assert res2.violations[0].tool_call_id == "c2"


def test_repair_tool_pairing_invariants() -> None:
    """Repair damaged conversation: purge orphan results and trim unclosed calls."""
    corrupted_messages = [
        HumanMessage(content="Start"),
        ToolMessage(content="Orphan result", tool_call_id="bad_call"),
        AIMessage(
            content="Partial tools",
            tool_calls=[
                {"name": "t1", "args": {}, "id": "valid_call"},
                {"name": "t2", "args": {}, "id": "abandoned_call"},
            ],
        ),
        ToolMessage(content="Valid result", tool_call_id="valid_call"),
        HumanMessage(content="Continue"),
    ]

    repaired = repair_tool_pairing_invariants(corrupted_messages)
    val = validate_tool_pairing_invariants(repaired)
    assert val.is_valid

    # Verify orphan is removed
    assert not any(isinstance(m, ToolMessage) and getattr(m, "tool_call_id", "") == "bad_call" for m in repaired)

    # Verify unclosed tool call was trimmed from AIMessage
    ai_msgs = [m for m in repaired if isinstance(m, AIMessage)]
    assert len(ai_msgs) == 1
    remaining_calls = ai_msgs[0].tool_calls or []
    assert len(remaining_calls) == 1
    assert remaining_calls[0]["id"] == "valid_call"
