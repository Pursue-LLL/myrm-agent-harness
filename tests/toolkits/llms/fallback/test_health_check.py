"""Tests for lightweight health check functionality."""

from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage

from myrm_agent_harness.toolkits.llms.fallback.health_check import (
    lightweight_health_check,
    lightweight_health_check_with_retry,
)


@pytest.mark.asyncio
async def test_health_check_success():
    """Health check returns True when LLM responds."""
    mock_llm = AsyncMock()
    mock_llm.ainvoke.return_value = AIMessage(content="response")

    result = await lightweight_health_check(mock_llm)

    assert result is True
    mock_llm.ainvoke.assert_called_once()


@pytest.mark.asyncio
async def test_health_check_timeout():
    """Health check returns False on timeout."""
    mock_llm = AsyncMock()
    mock_llm.ainvoke.side_effect = TimeoutError()

    result = await lightweight_health_check(mock_llm)

    assert result is False


@pytest.mark.asyncio
async def test_health_check_exception():
    """Health check returns False on exception."""
    mock_llm = AsyncMock()
    mock_llm.ainvoke.side_effect = Exception("Connection error")

    result = await lightweight_health_check(mock_llm)

    assert result is False


@pytest.mark.asyncio
async def test_health_check_uses_minimal_tokens():
    """Health check uses minimal token configuration."""
    mock_llm = AsyncMock()
    mock_llm.ainvoke.return_value = AIMessage(content="ok")

    await lightweight_health_check(mock_llm, timeout_s=3.0)

    # Verify configuration
    call_args = mock_llm.ainvoke.call_args
    config = call_args.kwargs.get("config", {})

    assert config["max_tokens"] == 1
    assert config["timeout"] == 3.0


@pytest.mark.asyncio
async def test_health_check_with_retry_success_first_try():
    """Health check with retry succeeds on first attempt."""
    mock_llm = AsyncMock()
    mock_llm.ainvoke.return_value = AIMessage(content="ok")

    result = await lightweight_health_check_with_retry(mock_llm, max_attempts=3)

    assert result is True
    assert mock_llm.ainvoke.call_count == 1


@pytest.mark.asyncio
async def test_health_check_with_retry_success_second_try():
    """Health check with retry succeeds on second attempt."""
    mock_llm = AsyncMock()
    mock_llm.ainvoke.side_effect = [
        Exception("First attempt fails"),
        AIMessage(content="ok"),
    ]

    result = await lightweight_health_check_with_retry(mock_llm, max_attempts=3)

    assert result is True
    assert mock_llm.ainvoke.call_count == 2


@pytest.mark.asyncio
async def test_health_check_with_retry_all_fail():
    """Health check with retry returns False after all attempts."""
    mock_llm = AsyncMock()
    mock_llm.ainvoke.side_effect = Exception("Always fails")

    result = await lightweight_health_check_with_retry(mock_llm, max_attempts=2)

    assert result is False
    assert mock_llm.ainvoke.call_count == 2


@pytest.mark.asyncio
async def test_health_check_with_retry_custom_timeout():
    """Health check with retry uses custom timeout."""
    mock_llm = AsyncMock()
    mock_llm.ainvoke.return_value = AIMessage(content="ok")

    await lightweight_health_check_with_retry(mock_llm, max_attempts=2, timeout_s=10.0)

    # Verify first call uses custom timeout
    call_args = mock_llm.ainvoke.call_args
    config = call_args.kwargs.get("config", {})
    assert config["timeout"] == 10.0
