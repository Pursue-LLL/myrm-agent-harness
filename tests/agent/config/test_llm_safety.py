"""Test Provider Safety — normalize_messages is the production sanitize → dangling-repair pair."""

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from myrm_agent_harness.agent.config.llm_safety import normalize_messages


class TestNormalizeMessages:
    """Test message normalization logic."""

    def test_empty_messages(self) -> None:
        """Empty message list returns empty."""
        result = normalize_messages([])
        assert result == []

    def test_basic_human_ai_exchange(self) -> None:
        """Basic human-AI exchange passes through."""
        messages = [
            HumanMessage(content="Hello"),
            AIMessage(content="Hi there"),
        ]
        result = normalize_messages(messages)
        assert len(result) == 2
        assert result[0].content == "Hello"
        assert result[1].content == "Hi there"

    def test_valid_tool_call_pair(self) -> None:
        """Valid tool call-response pair preserved."""
        messages = [
            HumanMessage(content="run ls"),
            AIMessage(content="", tool_calls=[{"id": "call_1", "name": "bash", "args": {"command": "ls"}}]),
            ToolMessage(content="file.txt", tool_call_id="call_1"),
        ]
        result = normalize_messages(messages)
        assert len(result) == 3
        assert isinstance(result[1], AIMessage)
        assert len(result[1].tool_calls) == 1
        assert result[1].tool_calls[0]["id"] == "call_1"
        assert isinstance(result[2], ToolMessage)
        assert result[2].tool_call_id == "call_1"

    def test_invalid_tool_request_removed(self) -> None:
        """Tool request with no id is removed (skip - LangChain validates at construction)."""
        # Note: LangChain's AIMessage constructor validates tool_calls must have 'id'.
        # This test case is conceptually valid but cannot be constructed in LangChain.
        # In practice, invalid tool calls would be filtered by LangChain before reaching
        # normalize_messages(). This test is skipped.
        pytest.skip("LangChain validates tool_calls at construction, preventing invalid tool calls")

    def test_orphan_tool_response_removed(self) -> None:
        """Tool response with no matching request is removed."""
        messages = [
            HumanMessage(content="run ls"),
            ToolMessage(content="file.txt", tool_call_id="call_1"),  # No matching request
        ]
        result = normalize_messages(messages)
        # Should only keep HumanMessage
        assert len(result) == 1
        assert isinstance(result[0], HumanMessage)

    def test_duplicate_tool_response_removed(self) -> None:
        """Duplicate tool responses (same tool_call_id) are removed."""
        messages = [
            HumanMessage(content="run ls"),
            AIMessage(content="", tool_calls=[{"id": "call_1", "name": "bash", "args": {"command": "ls"}}]),
            ToolMessage(content="file.txt", tool_call_id="call_1"),
            ToolMessage(content="file2.txt", tool_call_id="call_1"),  # Duplicate
        ]
        result = normalize_messages(messages)
        # sanitize_tool_history keep-last runs before pairing normalization
        assert len(result) == 3
        tool_messages = [msg for msg in result if isinstance(msg, ToolMessage)]
        assert len(tool_messages) == 1
        assert tool_messages[0].content == "file2.txt"

    def test_cross_turn_duplicate_ids_re_id_via_normalize(self) -> None:
        messages = [
            AIMessage(content="", tool_calls=[{"id": "call_x", "name": "grep_tool", "args": {}}]),
            ToolMessage(content="a", tool_call_id="call_x", name="grep_tool"),
            HumanMessage(content="continue"),
            AIMessage(content="", tool_calls=[{"id": "call_x", "name": "grep_tool", "args": {}}]),
            ToolMessage(content="b", tool_call_id="call_x", name="grep_tool"),
        ]
        result = normalize_messages(messages)
        ai_tool_ids = [tc["id"] for m in result if isinstance(m, AIMessage) for tc in (m.tool_calls or [])]
        assert len(ai_tool_ids) == len(set(ai_tool_ids))
        assert "call_x@2" in ai_tool_ids

    def test_mixed_valid_invalid_tool_calls(self) -> None:
        """AIMessage with mixed valid/invalid tool calls keeps only valid ones (skip - LangChain validates at construction)."""
        # Note: LangChain's AIMessage constructor validates tool_calls must have 'id'.
        # Cannot construct mixed valid/invalid tool calls in LangChain.
        # In practice, this validation happens before normalize_messages().
        pytest.skip("LangChain validates tool_calls at construction, preventing mixed valid/invalid")

    def test_system_messages_preserved(self) -> None:
        """SystemMessages are always preserved."""
        messages = [
            SystemMessage(content="You are a helpful assistant"),
            HumanMessage(content="Hello"),
            AIMessage(content="Hi"),
        ]
        result = normalize_messages(messages)
        assert len(result) == 3
        assert isinstance(result[0], SystemMessage)
        assert result[0].content == "You are a helpful assistant"

    def test_unanswered_tool_request_gets_a_synthetic_result(self) -> None:
        """A tool request without a result is answered, as the middleware chain does before a model call."""
        messages = [
            HumanMessage(content="run ls"),
            AIMessage(content="", tool_calls=[{"id": "call_1", "name": "bash", "args": {"command": "ls"}}]),
            # No ToolMessage response
        ]
        result = normalize_messages(messages)
        assert [type(msg) for msg in result] == [HumanMessage, AIMessage, ToolMessage]
        answer = result[2]
        assert isinstance(answer, ToolMessage)
        assert answer.tool_call_id == "call_1"

    def test_ai_message_with_content_and_unanswered_tools_keeps_its_request(self) -> None:
        """The request keeps its content and tool calls; only the missing result is synthesized."""
        messages = [
            HumanMessage(content="run ls"),
            AIMessage(
                content="I will run ls for you",
                tool_calls=[{"id": "call_1", "name": "bash", "args": {"command": "ls"}}],
            ),
            # No ToolMessage response
        ]
        result = normalize_messages(messages)
        assert [type(msg) for msg in result] == [HumanMessage, AIMessage, ToolMessage]
        ai_msg = result[1]
        assert isinstance(ai_msg, AIMessage)
        assert ai_msg.content == "I will run ls for you"
        assert [call["id"] for call in ai_msg.tool_calls] == ["call_1"]

    def test_empty_tool_result_is_kept(self) -> None:
        """A command with no output is a legitimate result; dropping it would leave its request unanswered."""
        messages = [
            HumanMessage(content="touch f"),
            AIMessage(content="", tool_calls=[{"id": "call_1", "name": "bash", "args": {"command": "touch f"}}]),
            ToolMessage(content="", tool_call_id="call_1"),
        ]
        result = normalize_messages(messages)
        assert len(result) == 3
        kept = result[2]
        assert isinstance(kept, ToolMessage)
        assert kept.tool_call_id == "call_1"
        assert kept.content == ""

    def test_well_formed_history_is_returned_unchanged(self) -> None:
        """A history the provider accepts comes back message-for-message identical (prompt-cache prefix)."""
        messages = [
            SystemMessage(content="You are a helpful assistant"),
            HumanMessage(content="run ls"),
            AIMessage(content="", tool_calls=[{"id": "call_1", "name": "bash", "args": {"command": "ls"}}]),
            ToolMessage(content="file.txt", tool_call_id="call_1"),
            AIMessage(content="done"),
        ]
        result = normalize_messages(messages)
        assert len(result) == len(messages)
        assert all(kept is original for kept, original in zip(result, messages, strict=True))


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
