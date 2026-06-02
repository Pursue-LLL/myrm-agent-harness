"""Test Provider Safety — Message normalization and LLM wrapping."""

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from myrm_agent_harness.agent.config.llm_safety import (
    SafetyWrappedChatModel,
    normalize_messages,
    wrap_chat_model_with_safety,
)


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
        # Should keep only first response
        assert len(result) == 3
        tool_messages = [msg for msg in result if isinstance(msg, ToolMessage)]
        assert len(tool_messages) == 1
        assert tool_messages[0].content == "file.txt"

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

    def test_unmatched_tool_request_removed(self) -> None:
        """Tool request without response is removed."""
        messages = [
            HumanMessage(content="run ls"),
            AIMessage(content="", tool_calls=[{"id": "call_1", "name": "bash", "args": {"command": "ls"}}]),
            # No ToolMessage response
        ]
        result = normalize_messages(messages)
        # Should only keep HumanMessage (AIMessage has unmatched tool call and no content)
        assert len(result) == 1
        assert isinstance(result[0], HumanMessage)

    def test_ai_message_with_content_and_unmatched_tools(self) -> None:
        """AIMessage with content but unmatched tools keeps content, drops tools."""
        messages = [
            HumanMessage(content="run ls"),
            AIMessage(
                content="I will run ls for you",
                tool_calls=[{"id": "call_1", "name": "bash", "args": {"command": "ls"}}],
            ),
            # No ToolMessage response
        ]
        result = normalize_messages(messages)
        # Should keep both messages, but AIMessage loses tool_calls
        assert len(result) == 2
        ai_msg = next(msg for msg in result if isinstance(msg, AIMessage))
        assert ai_msg.content == "I will run ls for you"
        assert len(ai_msg.tool_calls) == 0


class TestSafetyWrappedChatModel:
    """Test SafetyWrappedChatModel wrapper."""

    def test_wrap_already_wrapped_no_double_wrap(self) -> None:
        """Wrapping an already wrapped model should not double-wrap."""
        from unittest.mock import MagicMock

        mock_llm = MagicMock()
        wrapped = SafetyWrappedChatModel(mock_llm)
        double_wrapped = wrap_chat_model_with_safety(wrapped)
        # Should return same instance
        assert double_wrapped is wrapped

    def test_wrap_chat_model_returns_wrapped_instance(self) -> None:
        """wrap_chat_model_with_safety returns SafetyWrappedChatModel."""
        from unittest.mock import MagicMock

        mock_llm = MagicMock()
        wrapped = wrap_chat_model_with_safety(mock_llm)
        assert isinstance(wrapped, SafetyWrappedChatModel)
        assert wrapped._wrapped is mock_llm


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
