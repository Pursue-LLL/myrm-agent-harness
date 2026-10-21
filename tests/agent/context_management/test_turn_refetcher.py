"""Tests for Historical Turn Refetcher.

Validates single-turn on-demand verbatim retrieval and defensive vault://
zero-copy pointer offloading for large turn payloads.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from myrm_agent_harness.agent.context_management.strategies.summary.turn_refetcher import (
    HistoricalTurnRefetchResult,
    create_refetch_historical_turn_tool,
    refetch_historical_turn,
)


def test_refetch_out_of_bounds() -> None:
    """Return None when turn_index is negative or beyond message list length."""
    messages = [HumanMessage(content="Hello"), AIMessage(content="World")]

    assert refetch_historical_turn(messages, -1) is None
    assert refetch_historical_turn(messages, 2) is None
    assert refetch_historical_turn([], 0) is None


def test_refetch_inline_message() -> None:
    """Return verbatim inline content when payload is within max_inline_chars."""
    messages = [
        HumanMessage(content="First turn prompt"),
        ToolMessage(content="Tool execution output line 1", tool_call_id="call_1"),
    ]

    result = refetch_historical_turn(messages, 1, max_inline_chars=100)

    assert isinstance(result, HistoricalTurnRefetchResult)
    assert result.turn_index == 1
    assert result.is_vault_pointer is False
    assert "[Retrieved Historical Turn #1 (ToolMessage)]" in result.content
    assert "Tool execution output line 1" in result.content


def test_refetch_large_payload_offload_to_vault_pointer() -> None:
    """Safely degrade to zero-copy vault pointer when payload exceeds limit."""
    large_log = "START_OF_LOG\n" + ("x" * 3000) + "\nEND_OF_LOG"
    messages = [ToolMessage(content=large_log, tool_call_id="call_big")]

    result = refetch_historical_turn(
        messages,
        0,
        max_inline_chars=1000,
        chat_id="chat-test-123",
    )

    assert isinstance(result, HistoricalTurnRefetchResult)
    assert result.turn_index == 0
    assert result.is_vault_pointer is True
    assert "vault://chat-test-123/turns/0/transcript.log" in result.content
    assert "START_OF_LOG" in result.content
    assert "END_OF_LOG" in result.content
    # Inline content length should be strictly bounded (well below full log length)
    assert len(result.content) < 2000


def test_refetch_historical_turn_tool_success() -> None:
    """Tool correctly retrieves verbatim turn content via sync invoke."""
    messages = [
        HumanMessage(content="Task prompt 1"),
        AIMessage(content="Here is the execution plan."),
    ]
    tool = create_refetch_historical_turn_tool(lambda: messages, chat_id="chat-456")

    assert tool.name == "refetch_historical_turn"
    assert "exact error traces" in tool.description

    # Valid turn
    output = tool.invoke({"turn_index": 1})
    assert "[Retrieved Historical Turn #1 (AIMessage)]" in output
    assert "Here is the execution plan." in output


async def test_refetch_historical_turn_tool_async_and_bounds() -> None:
    """Tool returns informative bounds message when index does not exist."""
    messages = [HumanMessage(content="Hello")]
    tool = create_refetch_historical_turn_tool(lambda: messages)

    # Async invocation
    out_valid = await tool.ainvoke({"turn_index": 0})
    assert "Hello" in out_valid

    # Out of bounds
    out_invalid = await tool.ainvoke({"turn_index": 5})
    assert "Historical turn #5 not found" in out_invalid
    assert "Valid turn range is [0, 0]" in out_invalid
