"""Tests for ManagedLLM failover callback functionality."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from myrm_agent_harness.toolkits.llms.fallback import FailoverEvent, ManagedLLM


@pytest.mark.asyncio
async def test_managed_llm_callback_triggered_on_failover():
    """Test that callback is triggered when failover occurs."""
    # Create mock LLMs
    mock_main = MagicMock()
    mock_fallback = MagicMock()

    # Main fails, fallback succeeds
    async def main_agenerate(*args, **kwargs):
        raise Exception("Rate limit exceeded")

    async def fallback_agenerate(*args, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=HumanMessage(content="fallback response"))])

    mock_main.agenerate = AsyncMock(side_effect=main_agenerate)
    mock_fallback.agenerate = AsyncMock(side_effect=fallback_agenerate)

    # Create callback to track events
    callback_events = []

    async def on_failover(event: FailoverEvent) -> None:
        callback_events.append(event)

    # Create ManagedLLM with callback
    managed_llm = ManagedLLM(
        main_llm=mock_main,
        fallback_llm=mock_fallback,
        main_model_name="gpt-4",
        fallback_model_name="claude-3-opus",
        on_failover=on_failover,
    )

    # Invoke
    messages = [HumanMessage(content="test")]
    await managed_llm.ainvoke(messages)

    # Verify callback was called
    assert len(callback_events) == 1
    event = callback_events[0]
    assert event.from_model == "gpt-4"
    assert event.to_model == "claude-3-opus"
    assert event.error_message == "Rate limit exceeded"


@pytest.mark.asyncio
async def test_managed_llm_no_callback_when_main_succeeds():
    """Test that callback is not triggered when main LLM succeeds."""
    # Create mock LLMs
    mock_main = MagicMock()
    mock_fallback = MagicMock()

    # Main succeeds
    async def main_agenerate(*args, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=HumanMessage(content="main response"))])

    mock_main.agenerate = AsyncMock(side_effect=main_agenerate)
    mock_fallback.agenerate = AsyncMock()

    # Create callback to track events
    callback_events = []

    async def on_failover(event: FailoverEvent) -> None:
        callback_events.append(event)

    # Create ManagedLLM with callback
    managed_llm = ManagedLLM(
        main_llm=mock_main,
        fallback_llm=mock_fallback,
        main_model_name="gpt-4",
        fallback_model_name="claude-3-opus",
        on_failover=on_failover,
    )

    # Invoke
    messages = [HumanMessage(content="test")]
    await managed_llm.ainvoke(messages)

    # Verify callback was NOT called
    assert len(callback_events) == 0
    # Verify fallback was not called
    mock_fallback.agenerate.assert_not_called()


@pytest.mark.asyncio
async def test_managed_llm_without_callback():
    """Test that ManagedLLM works without callback (backward compatible)."""
    # Create mock LLMs
    mock_main = MagicMock()
    mock_fallback = MagicMock()

    # Main fails, fallback succeeds
    async def main_agenerate(*args, **kwargs):
        raise Exception("Rate limit exceeded")

    async def fallback_agenerate(*args, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=HumanMessage(content="fallback response"))])

    mock_main.agenerate = AsyncMock(side_effect=main_agenerate)
    mock_fallback.agenerate = AsyncMock(side_effect=fallback_agenerate)

    # Create ManagedLLM without callback
    managed_llm = ManagedLLM(
        main_llm=mock_main,
        fallback_llm=mock_fallback,
        main_model_name="gpt-4",
        fallback_model_name="claude-3-opus",
    )

    # Invoke - should not raise
    messages = [HumanMessage(content="test")]
    result = await managed_llm.ainvoke(messages)

    # Verify fallback was called
    assert result is not None


@pytest.mark.asyncio
async def test_managed_llm_callback_exception_does_not_fail_request():
    """Test that callback exception does not fail the entire request."""
    # Create mock LLMs
    mock_main = MagicMock()
    mock_fallback = MagicMock()

    # Main fails, fallback succeeds
    async def main_agenerate(*args, **kwargs):
        raise Exception("Rate limit exceeded")

    async def fallback_agenerate(*args, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=HumanMessage(content="fallback response"))])

    mock_main.agenerate = AsyncMock(side_effect=main_agenerate)
    mock_fallback.agenerate = AsyncMock(side_effect=fallback_agenerate)

    # Create callback that raises
    async def on_failover(event: FailoverEvent) -> None:
        raise Exception("Callback error")

    # Create ManagedLLM with failing callback
    managed_llm = ManagedLLM(
        main_llm=mock_main,
        fallback_llm=mock_fallback,
        main_model_name="gpt-4",
        fallback_model_name="claude-3-opus",
        on_failover=on_failover,
    )

    # Invoke - should not raise despite callback error
    messages = [HumanMessage(content="test")]
    result = await managed_llm.ainvoke(messages)

    # Verify request succeeded (ainvoke returns AIMessage, not ChatResult)
    assert result is not None
    assert result.content == "fallback response"
