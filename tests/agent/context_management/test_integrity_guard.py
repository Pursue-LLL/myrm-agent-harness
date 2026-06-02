"""Tests for tool-pair integrity normalization."""

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from myrm_agent_harness.agent.context_management.strategies.integrity_guard import ensure_tool_pair_integrity


def test_integrity_guard_trims_partially_matched_multi_tool_ai_message() -> None:
    messages = [
        HumanMessage(content="inspect project"),
        AIMessage(
            content="Running read and grep.",
            tool_calls=[
                {"id": "call_1", "name": "file_read_tool", "args": {"paths": ["a.py"]}},
                {"id": "call_2", "name": "grep_tool", "args": {"pattern": "TODO"}},
            ],
        ),
        ToolMessage(content="file content", tool_call_id="call_1", name="file_read_tool"),
        ToolMessage(content="orphan result", tool_call_id="call_x", name="bash"),
    ]

    normalized = ensure_tool_pair_integrity(messages)

    assert len(normalized) == 3
    assert isinstance(normalized[1], AIMessage)
    assert [tool_call["id"] for tool_call in normalized[1].tool_calls] == ["call_1"]
    assert isinstance(normalized[2], ToolMessage)
    assert normalized[2].tool_call_id == "call_1"


def test_integrity_guard_keeps_ai_content_when_all_tool_calls_are_removed() -> None:
    messages = [
        HumanMessage(content="continue"),
        AIMessage(
            content="I attempted a tool call before interruption.",
            tool_calls=[{"id": "call_1", "name": "bash", "args": {"command": "pwd"}}],
        ),
    ]

    normalized = ensure_tool_pair_integrity(messages)

    assert len(normalized) == 2
    assert isinstance(normalized[1], AIMessage)
    assert normalized[1].tool_calls == []
    assert "attempted" in str(normalized[1].content)


def test_integrity_guard_drops_empty_ai_message_without_matched_tools() -> None:
    messages = [
        HumanMessage(content="continue"),
        AIMessage(content="", tool_calls=[{"id": "call_1", "name": "bash", "args": {"command": "pwd"}}]),
    ]

    normalized = ensure_tool_pair_integrity(messages)

    assert normalized == [messages[0]]
