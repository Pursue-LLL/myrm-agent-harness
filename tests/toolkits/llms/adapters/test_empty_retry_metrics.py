"""Unit tests for empty retry metrics in ChatLiteLLM.

Tests cover:
- Metrics collection for sync/async/stream retries
- Success/failure counting
- Delay tracking
- Helper methods (get_total_retries, get_success_rate, etc.)
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import HumanMessage

from myrm_agent_harness.toolkits.llms.adapters.chat_model import ChatLiteLLM


@pytest.fixture
def chat_model():
    """Create ChatLiteLLM instance with mock client."""
    model = ChatLiteLLM(model="gpt-3.5-turbo")
    model.client = MagicMock()
    return model


@pytest.fixture
def messages():
    """Create test messages."""
    return [HumanMessage(content="test")]


def test_sync_retry_metrics_success(chat_model, messages):
    """Test sync retry metrics are updated on success after retry."""
    mock_response_empty = {"choices": [], "usage": {}}
    mock_response_success = {
        "choices": [{"message": {"role": "assistant", "content": "test"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20},
    }

    chat_model.client.completion.side_effect = [
        mock_response_empty,
        mock_response_success,
    ]

    _ = chat_model._generate(messages)

    metrics = chat_model.retry_metrics
    assert metrics.sync_retry_count == 1  # One retry
    assert metrics.sync_success_after_retry == 1  # Success on retry
    assert metrics.total_retry_delay_ms > 0  # Delay recorded


def test_sync_retry_metrics_exhausted(chat_model, messages):
    """Test sync retry metrics when retries are exhausted."""
    mock_response_empty = {"choices": [], "usage": {}}
    chat_model.client.completion.return_value = mock_response_empty

    from myrm_agent_harness.toolkits.llms.adapters.chat_model import EmptyChoicesError

    with pytest.raises(EmptyChoicesError):
        chat_model._generate(messages)

    metrics = chat_model.retry_metrics
    assert metrics.sync_retry_count == 3  # 3 retries (default max_attempts)
    assert metrics.sync_success_after_retry == 0  # No success
    assert metrics.total_retry_delay_ms > 0  # Delay recorded


@pytest.mark.asyncio
async def test_async_retry_metrics_success(chat_model, messages):
    """Test async retry metrics are updated on success after retry."""
    mock_response_empty = {"choices": [], "usage": {}}
    mock_response_success = {
        "choices": [{"message": {"role": "assistant", "content": "test"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20},
    }

    mock_acreate = AsyncMock()
    mock_acreate.side_effect = [
        mock_response_empty,
        mock_response_success,
    ]
    chat_model.client.acreate = mock_acreate

    _ = await chat_model._agenerate(messages)

    metrics = chat_model.retry_metrics
    assert metrics.async_retry_count == 1
    assert metrics.async_success_after_retry == 1
    assert metrics.total_retry_delay_ms > 0


def test_stream_retry_metrics_exhausted(chat_model, messages):
    """Test stream retry metrics when retries are exhausted."""

    def mock_stream(*args: Any, **kwargs: Any) -> Any:
        return iter([])

    chat_model.client.completion.side_effect = mock_stream

    from myrm_agent_harness.toolkits.llms.adapters.chat_model import EmptyStreamError

    with pytest.raises(EmptyStreamError):
        list(chat_model._stream(messages))

    metrics = chat_model.retry_metrics
    assert metrics.stream_retry_count == 3
    assert metrics.stream_success_after_retry == 0
    assert metrics.total_retry_delay_ms > 0


def test_metrics_helper_methods(chat_model, messages):
    """Test metrics helper methods."""
    # Simulate some retries
    mock_response_empty = {"choices": [], "usage": {}}
    mock_response_success = {
        "choices": [{"message": {"role": "assistant", "content": "test"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20},
    }

    chat_model.client.completion.side_effect = [
        mock_response_empty,
        mock_response_success,
    ]
    _ = chat_model._generate(messages)

    metrics = chat_model.retry_metrics

    # Test helper methods
    assert metrics.get_total_retries() == 1
    assert metrics.get_total_successes() == 1
    assert metrics.get_success_rate() == 1.0  # 100% success
    assert metrics.get_avg_retry_delay_ms() > 0

    # Test to_dict()
    metrics_dict = metrics.to_dict()
    assert isinstance(metrics_dict, dict)
    assert "sync_retry_count" in metrics_dict
    assert "total_retry_delay_ms" in metrics_dict


def test_metrics_isolation_per_instance():
    """Test metrics are isolated per instance."""
    model1 = ChatLiteLLM(model="gpt-3.5-turbo")
    model2 = ChatLiteLLM(model="gpt-4")

    # Verify different instances have different metrics
    assert model1.retry_metrics is not model2.retry_metrics

    # Simulate retry on model1
    model1._retry_metrics.sync_retry_count = 5

    # Verify model2 is not affected
    assert model2.retry_metrics.sync_retry_count == 0
