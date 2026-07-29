"""Tests for retention_helpers."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from myrm_agent_harness.agent.context_management.infra.retention_helpers import (
    extract_failed_tool_call_ids,
    find_keep_recent_prune_cutoff,
    should_retain_tool_message,
)


def test_extract_failed_tool_call_ids_from_metadata() -> None:
    metadata = {
        "compression_intent": {
            "failed_tool_call_ids": ["call_1", "", 123],
        }
    }
    assert extract_failed_tool_call_ids(metadata) == frozenset({"call_1"})


def test_should_retain_tool_message_for_failed_id() -> None:
    msg = ToolMessage(content="ok", tool_call_id="call_failed", name="bash")
    assert should_retain_tool_message(msg, frozenset({"call_failed"})) is True


def test_should_retain_tool_message_for_error_heuristic() -> None:
    msg = ToolMessage(
        content="Traceback (most recent call last):\nValueError: boom",
        tool_call_id="call_x",
        name="bash",
    )
    assert should_retain_tool_message(msg, frozenset()) is True


def test_find_keep_recent_prune_cutoff_protects_recent_groups() -> None:
    messages = [
        HumanMessage(content="hi"),
        AIMessage(content="", tool_calls=[{"id": "tc1", "name": "grep_tool", "args": {}}]),
        ToolMessage(content="result1", name="grep_tool", tool_call_id="tc1"),
        AIMessage(content="", tool_calls=[{"id": "tc2", "name": "web_search", "args": {}}]),
        ToolMessage(content="result2", name="web_search", tool_call_id="tc2"),
    ]
    assert find_keep_recent_prune_cutoff(messages, keep_recent_calls=5) == 2


def test_find_keep_recent_prune_cutoff_with_many_groups() -> None:
    messages: list = [HumanMessage(content="hi")]
    for i in range(6):
        tc_id = f"tc{i}"
        messages.append(
            AIMessage(content="", tool_calls=[{"id": tc_id, "name": "tool", "args": {}}])
        )
        messages.append(ToolMessage(content=f"result{i}", name="tool", tool_call_id=tc_id))

    # keep 5 of 6 groups -> first protected group is tc1 at message index 4
    assert find_keep_recent_prune_cutoff(messages, keep_recent_calls=5) == 4
