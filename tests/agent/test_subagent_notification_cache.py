"""Tests for subagent notification Prompt Cache preservation.

Verifies that async subagent completion notifications do NOT inject
dynamic HumanMessages into the conversation, preserving LLM prompt caching
efficiency (10x cost reduction).
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from myrm_agent_harness.agent.streaming.stream_executor import StreamExecutor
from myrm_agent_harness.agent.streaming.types import AgentEventType

if TYPE_CHECKING:
    pass


@pytest.fixture
def mock_context() -> MagicMock:
    """Create a mock WrappedContext."""
    ctx = MagicMock()
    ctx.stats.was_cancelled = False
    ctx.drain_subagent_notifications = MagicMock()
    ctx.output_queue = AsyncMock()
    ctx.message_id = "test-msg-123"
    ctx.agent_input = {"messages": []}
    return ctx


@pytest.fixture
def executor(mock_context: MagicMock) -> StreamExecutor:
    """Create a StreamExecutor with mock context."""
    executor = StreamExecutor.__new__(StreamExecutor)
    executor._ctx = mock_context
    executor.streaming_final_answer = False

    compactor = MagicMock()
    compactor.put = AsyncMock()
    executor._compactor = compactor
    return executor


@pytest.mark.asyncio
async def test_no_notification_returns_false(
    executor: StreamExecutor, mock_context: MagicMock
) -> None:
    """Test _handle_subagent_notifications returns False when no notification."""
    mock_context.drain_subagent_notifications.return_value = ""

    result = await executor._handle_subagent_notifications([])

    assert result is False
    mock_context.output_queue.put.assert_not_called()


@pytest.mark.asyncio
async def test_notification_no_message_injection(
    executor: StreamExecutor, mock_context: MagicMock
) -> None:
    """Test that subagent notification does NOT inject HumanMessage."""
    notification_text = """[Subagent 'worker' (task_id=abc123) completed successfully] (2.1s)
Result: Python 3.13.1 released
"""
    mock_context.drain_subagent_notifications.return_value = notification_text

    original_messages = [
        SystemMessage(content="You are a helpful agent"),
        HumanMessage(content="Search Python version"),
    ]
    mock_context.agent_input = {"messages": original_messages.copy()}

    result = await executor._handle_subagent_notifications([])

    # Should return False (no new turn triggered)
    assert result is False

    # Critical: messages should NOT be modified
    assert mock_context.agent_input["messages"] == original_messages
    assert len(mock_context.agent_input["messages"]) == 2


@pytest.mark.asyncio
async def test_notification_emits_sse_event(
    executor: StreamExecutor, mock_context: MagicMock
) -> None:
    """Test that SSE event is emitted for frontend notification."""
    notification_text = "[Subagent completed]"
    mock_context.drain_subagent_notifications.return_value = notification_text

    await executor._handle_subagent_notifications([])

    executor._compactor.put.assert_awaited_once()
    call_args = executor._compactor.put.call_args[0][0]

    assert call_args["type"] == AgentEventType.SUBAGENT_COMPLETION.value
    assert call_args["data"] == notification_text
    assert call_args["messageId"] == "test-msg-123"


@pytest.mark.asyncio
async def test_prompt_cache_prefix_preservation(
    executor: StreamExecutor, mock_context: MagicMock
) -> None:
    """Test that message prefix remains stable for Prompt Cache."""
    notification_text = "[Subagent completed with result XYZ]"
    mock_context.drain_subagent_notifications.return_value = notification_text

    # Simulate Turn 1
    turn1_messages = [
        SystemMessage(content="System prompt"),
        HumanMessage(content="User query 1"),
    ]
    mock_context.agent_input = {"messages": turn1_messages.copy()}

    await executor._handle_subagent_notifications(turn1_messages)

    messages_after_turn1 = mock_context.agent_input["messages"]

    # Simulate Turn 2 (user follows up)
    turn2_messages = [*messages_after_turn1, HumanMessage(content="User query 2")]
    mock_context.agent_input = {"messages": turn2_messages}

    # Verify prefix stability: first 2 messages unchanged
    assert turn2_messages[0] == turn1_messages[0]  # SystemMessage unchanged
    assert turn2_messages[1] == turn1_messages[1]  # First HumanMessage unchanged
    assert len(turn2_messages) == 3  # Only new HumanMessage added


@pytest.mark.asyncio
async def test_multiple_subagent_completions(
    executor: StreamExecutor, mock_context: MagicMock
) -> None:
    """Test handling multiple subagent completions in one notification."""
    notification_text = """[Subagent 'worker1' (task_id=abc) completed] (1.0s)
Result: Task 1 done
[Subagent 'worker2' (task_id=def) completed] (2.0s)
Result: Task 2 done
"""
    mock_context.drain_subagent_notifications.return_value = notification_text

    original_messages = [SystemMessage(content="System")]
    mock_context.agent_input = {"messages": original_messages.copy()}

    await executor._handle_subagent_notifications(original_messages)

    # No injection even for multiple completions
    assert mock_context.agent_input["messages"] == original_messages

    executor._compactor.put.assert_awaited_once()
    call_args = executor._compactor.put.call_args[0][0]
    assert notification_text in call_args["data"]


@pytest.mark.asyncio
async def test_cancelled_context_no_processing(
    executor: StreamExecutor, mock_context: MagicMock
) -> None:
    """Test that cancelled context skips notification processing."""
    mock_context.stats.was_cancelled = True
    mock_context.drain_subagent_notifications.return_value = "[Completed]"

    result = await executor._handle_subagent_notifications([])

    assert result is False
    mock_context.drain_subagent_notifications.assert_not_called()
    executor._compactor.put.assert_not_called()


@pytest.mark.asyncio
async def test_notification_logging(
    executor: StreamExecutor, mock_context: MagicMock
) -> None:
    """Test that notification is logged with preview."""
    notification_text = "A" * 200  # Long notification
    mock_context.drain_subagent_notifications.return_value = notification_text

    with patch(
        "myrm_agent_harness.agent.streaming.stream_recovery_continuation.logger"
    ) as mock_logger:
        await executor._handle_subagent_notifications([])

        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args
        assert "Subagent completion detected" in call_args[0][0]
