"""Unit tests for empty response retry mechanism in ChatLiteLLM.

Tests cover:
- Sync retry (success and exhausted)
- Async retry (success and exhausted)
- Stream retry (success and exhausted)
- Config validation and disabled retry
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import HumanMessage

from myrm_agent_harness.toolkits.llms.adapters.chat_model import (
    ChatLiteLLM,
    EmptyChoicesError,
    EmptyStreamError,
)


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


# Sync tests


def test_sync_retry_success(chat_model, messages):
    """Test sync retry succeeds on second attempt."""
    # First call returns empty choices, second call succeeds
    mock_response_empty = {"choices": [], "usage": {}}
    mock_response_success = {
        "choices": [{"message": {"role": "assistant", "content": "test"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20},
    }

    chat_model.client.completion.side_effect = [
        mock_response_empty,  # First attempt fails
        mock_response_success,  # Second attempt succeeds
    ]

    result = chat_model._generate(messages)

    assert len(result.generations) == 1
    assert result.generations[0].message.content == "test"
    assert chat_model.client.completion.call_count == 2


def test_sync_retry_exhausted(chat_model, messages):
    """Test sync retry fails after max attempts."""
    mock_response_empty = {"choices": [], "usage": {}}
    chat_model.client.completion.return_value = mock_response_empty

    with pytest.raises(EmptyChoicesError):
        chat_model._generate(messages)

    assert chat_model.client.completion.call_count == 3  # Default max_attempts


def test_sync_retry_disabled(chat_model, messages):
    """Test sync retry disabled via config."""
    chat_model.empty_retry_enabled = False
    mock_response_empty = {"choices": [], "usage": {}}
    chat_model.client.completion.return_value = mock_response_empty

    with pytest.raises(EmptyChoicesError):
        chat_model._generate(messages)

    assert chat_model.client.completion.call_count == 1  # No retry


def test_sync_non_empty_error_no_retry(chat_model, messages):
    """Test non-EmptyChoicesError exceptions are not retried."""
    chat_model.client.completion.side_effect = ValueError("test error")

    with pytest.raises(ValueError, match="test error"):
        chat_model._generate(messages)

    assert chat_model.client.completion.call_count == 1  # No retry


# Async tests


@pytest.mark.asyncio
async def test_async_retry_success(chat_model, messages):
    """Test async retry succeeds on second attempt."""
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

    result = await chat_model._agenerate(messages)

    assert len(result.generations) == 1
    assert result.generations[0].message.content == "test"
    assert mock_acreate.call_count == 2


@pytest.mark.asyncio
async def test_async_retry_exhausted(chat_model, messages):
    """Test async retry fails after max attempts."""
    mock_response_empty = {"choices": [], "usage": {}}
    mock_acreate = AsyncMock(return_value=mock_response_empty)
    chat_model.client.acreate = mock_acreate

    with pytest.raises(EmptyChoicesError):
        await chat_model._agenerate(messages)

    assert mock_acreate.call_count == 3


@pytest.mark.asyncio
async def test_async_retry_disabled(chat_model, messages):
    """Test async retry disabled via config."""
    chat_model.empty_retry_enabled = False
    mock_response_empty = {"choices": [], "usage": {}}
    mock_acreate = AsyncMock(return_value=mock_response_empty)
    chat_model.client.acreate = mock_acreate

    with pytest.raises(EmptyChoicesError):
        await chat_model._agenerate(messages)

    assert mock_acreate.call_count == 1


# Stream tests


def test_stream_normal_response_no_retry(chat_model, messages):
    """Test stream with normal response does not trigger retry."""

    def mock_stream(*args: Any, **kwargs: Any) -> Any:
        return iter(
            [
                {"choices": [{"delta": {"role": "assistant", "content": "test"}, "finish_reason": None, "index": 0}]},
                {
                    "choices": [{"delta": {}, "finish_reason": "stop", "index": 0}],
                    "usage": {"total_tokens": 30},
                },
            ]
        )

    chat_model.client.completion.side_effect = mock_stream

    chunks = list(chat_model._stream(messages))

    assert len(chunks) > 0
    # Should only call once (no retry needed)
    assert chat_model.client.completion.call_count == 1


def test_stream_empty_retry_exhausted(chat_model, messages):
    """Test stream retry fails after max attempts."""

    def mock_stream(*args: Any, **kwargs: Any) -> Any:
        return iter([])  # Always return empty stream

    chat_model.client.completion.side_effect = mock_stream

    with pytest.raises(EmptyStreamError):
        list(chat_model._stream(messages))

    assert chat_model.client.completion.call_count == 3


def test_stream_retry_disabled(chat_model, messages):
    """Test stream retry disabled via config."""
    chat_model.empty_retry_enabled = False

    def mock_stream(*args: Any, **kwargs: Any) -> Any:
        return iter([])

    chat_model.client.completion.side_effect = mock_stream

    with pytest.raises(EmptyStreamError):
        list(chat_model._stream(messages))

    assert chat_model.client.completion.call_count == 1


def test_stream_end_to_end_tool_call_recovery(chat_model, messages):
    """Streamed tool-call chunks are recovered into the final AIMessage."""

    schema = {
        "type": "function",
        "function": {
            "name": "bash_tool",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
    }

    def mock_stream(*args: Any, **kwargs: Any) -> Any:
        return iter(
            [
                {
                    "choices": [
                        {
                            "delta": {
                                "role": "assistant",
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call_1",
                                        "function": {"name": "bash_tool", "arguments": '{"command":"echo '},
                                    }
                                ],
                            },
                            "finish_reason": None,
                            "index": 0,
                        }
                    ]
                },
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "function": {"arguments": '\\"hi\\" &amp;&amp; ls"}'},
                                    }
                                ]
                            },
                            "finish_reason": None,
                            "index": 0,
                        }
                    ]
                },
                {
                    "choices": [{"delta": {}, "finish_reason": "stop", "index": 0}],
                    "usage": {"total_tokens": 30},
                },
            ]
        )

    chat_model.client.completion.side_effect = mock_stream

    result = chat_model._generate(messages, streaming=True, tools=[schema])

    assert len(result.generations) == 1
    ai_message = result.generations[0].message
    assert ai_message.tool_calls[0]["name"] == "bash_tool"
    assert ai_message.tool_calls[0]["args"]["command"] == 'echo "hi" && ls'
    assert ai_message.additional_kwargs.get("tool_call_recovery", []) == []


# Config validation tests


def test_config_max_attempts_validation():
    """Test max_attempts validation (1-10)."""
    # Valid range
    model = ChatLiteLLM(model="test", empty_retry_max_attempts=5)
    assert model.empty_retry_max_attempts == 5

    # Below minimum
    with pytest.raises(ValueError):
        ChatLiteLLM(model="test", empty_retry_max_attempts=0)

    # Above maximum
    with pytest.raises(ValueError):
        ChatLiteLLM(model="test", empty_retry_max_attempts=11)


def test_config_delay_validation():
    """Test delay validation (0.1-10.0)."""
    # Valid range
    model = ChatLiteLLM(model="test", empty_retry_delay=1.5)
    assert model.empty_retry_delay == 1.5

    # Below minimum
    with pytest.raises(ValueError):
        ChatLiteLLM(model="test", empty_retry_delay=0.05)

    # Above maximum
    with pytest.raises(ValueError):
        ChatLiteLLM(model="test", empty_retry_delay=15.0)
