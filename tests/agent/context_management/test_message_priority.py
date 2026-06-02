"""Tests for message priority classification."""

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from myrm_agent_harness.agent.context_management.infra.message_priority import (
    MessagePriority,
    classify_message_priority,
)


class TestPriorityClassification:
    """Test message priority classification logic."""

    def test_human_message_always_critical(self) -> None:
        """Human messages are always CRITICAL_USER."""
        msg = HumanMessage(content="Hello")
        assert classify_message_priority(msg, is_last_iteration=False) == MessagePriority.CRITICAL_USER
        assert classify_message_priority(msg, is_last_iteration=True) == MessagePriority.CRITICAL_USER

    def test_ai_message_final_iteration(self) -> None:
        """AI messages in final iteration are CRITICAL_FINAL."""
        msg = AIMessage(content="Final response")
        assert classify_message_priority(msg, is_last_iteration=True) == MessagePriority.CRITICAL_FINAL

    def test_ai_message_with_tool_calls(self) -> None:
        """AI messages with tool calls are HIGH_TOOL_CALL."""
        msg = AIMessage(
            content="Calling tool", tool_calls=[{"name": "search", "args": {"query": "test"}, "id": "call_123"}]
        )
        assert classify_message_priority(msg, is_last_iteration=False) == MessagePriority.HIGH_TOOL_CALL
        assert classify_message_priority(msg, is_last_iteration=True) == MessagePriority.HIGH_TOOL_CALL

    def test_ai_message_reasoning(self) -> None:
        """AI messages without tool calls (non-final) are MEDIUM_REASONING."""
        msg = AIMessage(content="I think...")
        assert classify_message_priority(msg, is_last_iteration=False) == MessagePriority.MEDIUM_REASONING

    def test_tool_message_error(self) -> None:
        """Tool messages with errors are HIGH_TOOL_ERROR."""
        msg = ToolMessage(content="[ERROR] Connection refused", tool_call_id="call_123")
        assert classify_message_priority(msg, is_last_iteration=False) == MessagePriority.HIGH_TOOL_ERROR

        msg2 = ToolMessage(content="error: timeout occurred", tool_call_id="call_456")
        assert classify_message_priority(msg2, is_last_iteration=False) == MessagePriority.HIGH_TOOL_ERROR

    def test_tool_message_with_summary(self) -> None:
        """Tool messages with embedded summary are MEDIUM_TOOL_SUMMARY."""
        msg = ToolMessage(
            content="Results...\nExecution Summary (3 steps): Created files\n==========", tool_call_id="call_123"
        )
        assert classify_message_priority(msg, is_last_iteration=False) == MessagePriority.MEDIUM_TOOL_SUMMARY

    def test_tool_message_success(self) -> None:
        """Tool messages (success, no summary) are LOW_TOOL_SUCCESS."""
        msg = ToolMessage(content="Operation completed successfully.", tool_call_id="call_123")
        assert classify_message_priority(msg, is_last_iteration=False) == MessagePriority.LOW_TOOL_SUCCESS

    def test_failed_tool_call_id_elevates_success_tool_message(self) -> None:
        """Structured failed-tool metadata should protect a nominally successful result."""
        msg = ToolMessage(content="Operation completed successfully.", tool_call_id="call_failed")

        assert (
            classify_message_priority(msg, is_last_iteration=False, failed_tool_call_ids=frozenset({"call_failed"}))
            == MessagePriority.HIGH_TOOL_ERROR
        )


class TestPriorityOrdering:
    """Test priority ordering (lower value = higher priority)."""

    def test_priority_ordering(self) -> None:
        """Verify priority ordering is correct."""
        assert MessagePriority.CRITICAL_USER < MessagePriority.CRITICAL_FINAL
        assert MessagePriority.CRITICAL_FINAL < MessagePriority.HIGH_TOOL_CALL
        assert MessagePriority.HIGH_TOOL_CALL < MessagePriority.MEDIUM_REASONING
        assert MessagePriority.MEDIUM_REASONING < MessagePriority.LOW_TOOL_SUCCESS

    def test_priority_values(self) -> None:
        """Verify expected priority values."""
        assert MessagePriority.CRITICAL_USER == 0
        assert MessagePriority.CRITICAL_FINAL == 1
        assert MessagePriority.HIGH_TOOL_CALL == 2
        assert MessagePriority.HIGH_TOOL_ERROR == 2  # Same as tool call
        assert MessagePriority.MEDIUM_REASONING == 3
        assert MessagePriority.MEDIUM_TOOL_SUMMARY == 3  # Same as reasoning
        assert MessagePriority.LOW_TOOL_SUCCESS == 4
