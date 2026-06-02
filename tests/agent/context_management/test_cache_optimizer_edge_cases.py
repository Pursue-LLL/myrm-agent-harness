"""Tests for ExplicitCacheProcessor edge cases and boundary conditions."""

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from myrm_agent_harness.agent.context_management.pipeline.base import ProcessorContext
from myrm_agent_harness.agent.context_management.pipeline.processors.cache_optimizer import ExplicitCacheProcessor


@pytest.mark.asyncio
async def test_process_empty_messages() -> None:
    """Handle empty message list gracefully."""
    processor = ExplicitCacheProcessor()
    context = ProcessorContext(messages=[], user_query="test")
    context.metadata["model_name"] = "anthropic/claude-3-5-sonnet"

    result = await processor.process(context)

    # Should not crash, returns context as-is
    assert result.messages == []


@pytest.mark.asyncio
async def test_process_single_message() -> None:
    """Handle single message with breakpoint at index 0."""
    processor = ExplicitCacheProcessor()
    messages = [SystemMessage(content="System prompt")]
    context = ProcessorContext(messages=messages, user_query="test")
    context.metadata["model_name"] = "anthropic/claude-3-5-sonnet"

    result = await processor.process(context)

    # Single message should get a breakpoint at index 0
    assert len(result.messages) == 1
    assert hasattr(result.messages[0], "additional_kwargs")


@pytest.mark.asyncio
async def test_process_non_anthropic_model() -> None:
    """Skip cache_control injection for non-Anthropic models (still processes)."""
    processor = ExplicitCacheProcessor()
    messages = [
        SystemMessage(content="System"),
        HumanMessage(content="Hello"),
    ]
    context = ProcessorContext(messages=messages, user_query="test")
    context.metadata["model_name"] = "openai/gpt-4"  # Non-Anthropic

    result = await processor.process(context)

    # Processor still runs (calculates breakpoints), but doesn't matter since
    # LiteLLM ignores cache_control for non-Anthropic providers
    assert len(result.messages) == 2


@pytest.mark.asyncio
async def test_process_without_model_name() -> None:
    """Handle missing model_name gracefully."""
    processor = ExplicitCacheProcessor()
    messages = [
        SystemMessage(content="System"),
        HumanMessage(content="Hello"),
    ]
    context = ProcessorContext(messages=messages, user_query="test")
    # No model_name in metadata

    result = await processor.process(context)

    # Should not crash, returns context as-is
    assert result is not None


@pytest.mark.asyncio
async def test_should_process_returns_false_for_non_anthropic() -> None:
    """should_process() returns False for non-Anthropic models."""
    processor = ExplicitCacheProcessor()
    context = ProcessorContext(messages=[HumanMessage(content="test")], user_query="test")
    context.metadata["model_name"] = "openai/gpt-4"

    should_process = await processor.should_process(context)

    assert should_process is False


@pytest.mark.asyncio
async def test_should_process_returns_true_for_anthropic() -> None:
    """should_process() returns True for Anthropic models."""
    processor = ExplicitCacheProcessor()
    context = ProcessorContext(messages=[HumanMessage(content="test")], user_query="test")
    context.metadata["model_name"] = "anthropic/claude-3-5-sonnet"

    should_process = await processor.should_process(context)

    assert should_process is True


@pytest.mark.asyncio
async def test_process_with_compression_metadata() -> None:
    """Track compression_count from metadata."""
    processor = ExplicitCacheProcessor()
    messages = [
        SystemMessage(content="System"),
        HumanMessage(content="User query"),
    ]
    context = ProcessorContext(messages=messages, user_query="test")
    context.metadata["model_name"] = "anthropic/claude-3-5-sonnet"
    context.metadata["compression_count"] = 2  # Simulate 2 compressions

    await processor.process(context)

    # Just verify it doesn't crash with compression metadata
    assert context.metadata["compression_count"] == 2
