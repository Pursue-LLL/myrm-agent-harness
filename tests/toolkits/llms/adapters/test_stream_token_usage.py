"""Unit tests for stream token usage collection via sentinel chunk.

Verifies that after finalize_stream records usage, an empty sentinel
ChatGenerationChunk is yielded (when there's no tool call), allowing
downstream dispatch to collect pending token events.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessageChunk, HumanMessage
from langchain_core.outputs import ChatGenerationChunk

from myrm_agent_harness.toolkits.llms.adapters.chat_model import ChatLiteLLM
from myrm_agent_harness.utils.token_economics.tracker import (
    get_pending_token_events,
    init_token_tracker,
)


def _make_stream_chunks(*, include_usage: bool = True) -> list[dict[str, Any]]:
    """Create a list of mock LiteLLM stream chunks."""
    chunks = [
        {
            "id": "chatcmpl-1",
            "object": "chat.completion.chunk",
            "model": "test-model",
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": "Hello"},
                    "finish_reason": None,
                }
            ],
        },
        {
            "id": "chatcmpl-1",
            "object": "chat.completion.chunk",
            "model": "test-model",
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": " world"},
                    "finish_reason": "stop",
                }
            ],
        },
    ]
    if include_usage:
        chunks.append(
            {
                "id": "chatcmpl-1",
                "object": "chat.completion.chunk",
                "model": "test-model",
                "choices": [],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                },
            }
        )
    return chunks


def _make_tool_call_stream_chunks() -> list[dict[str, Any]]:
    """Create stream chunks containing a tool call."""
    return [
        {
            "id": "chatcmpl-2",
            "object": "chat.completion.chunk",
            "model": "test-model",
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_abc123",
                                "type": "function",
                                "function": {"name": "get_weather", "arguments": ""},
                            }
                        ],
                    },
                    "finish_reason": None,
                }
            ],
        },
        {
            "id": "chatcmpl-2",
            "object": "chat.completion.chunk",
            "model": "test-model",
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "function": {"arguments": '{"city":"SF"}'},
                            }
                        ]
                    },
                    "finish_reason": "tool_calls",
                }
            ],
        },
        {
            "id": "chatcmpl-2",
            "object": "chat.completion.chunk",
            "model": "test-model",
            "choices": [],
            "usage": {
                "prompt_tokens": 20,
                "completion_tokens": 10,
                "total_tokens": 30,
            },
        },
    ]


class _MockModelResponse:
    """Simulates LiteLLM's ModelResponse with attribute access."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        return self._data.get(name)

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __contains__(self, key: str) -> bool:
        return key in self._data

    def json(self, **kwargs: Any) -> str:
        import json
        return json.dumps(self._data)


def _mock_stream(chunks: list[dict[str, Any]]):
    """Create a sync iterable of mock ModelResponse objects."""
    return iter([_MockModelResponse(c) for c in chunks])


async def _mock_astream(chunks: list[dict[str, Any]]):
    """Create an async iterable of mock ModelResponse objects."""
    for c in chunks:
        yield _MockModelResponse(c)


async def _awaitable_astream(chunks: list[dict[str, Any]]):
    """Return an awaitable that resolves to an async iterator."""
    return _mock_astream(chunks)


@pytest.fixture(autouse=True)
def _setup_tracker():
    """Ensure token tracker is initialized for each test."""
    init_token_tracker()


class TestSyncStreamSentinel:
    """Tests for sync _stream sentinel chunk behavior."""

    def test_yields_sentinel_when_no_tool_call(self):
        """Sentinel chunk is yielded after finalize_stream when no tool call."""
        model = ChatLiteLLM(model="openai/test-model")
        model.client = MagicMock()
        chunks = _make_stream_chunks(include_usage=True)
        model.client.completion = MagicMock(return_value=_mock_stream(chunks))

        results = list(model._stream([HumanMessage(content="hi")]))

        # Last chunk should be the empty sentinel
        last = results[-1]
        assert isinstance(last, ChatGenerationChunk)
        assert last.message.content == ""
        assert isinstance(last.message, AIMessageChunk)

    def test_token_usage_recorded_after_stream(self):
        """Token usage is correctly recorded and available via get_pending_token_events."""
        model = ChatLiteLLM(model="openai/test-model")
        model.client = MagicMock()
        chunks = _make_stream_chunks(include_usage=True)
        model.client.completion = MagicMock(return_value=_mock_stream(chunks))

        list(model._stream([HumanMessage(content="hi")]))

        events = get_pending_token_events()
        assert len(events) == 1
        usage = events[0]["usage"]
        assert usage["prompt_tokens"] == 10
        assert usage["completion_tokens"] == 5
        assert usage["total_tokens"] == 15

    def test_tool_call_stream_still_records_usage(self):
        """Token usage is recorded even in tool call streams."""
        model = ChatLiteLLM(model="openai/test-model")
        model.client = MagicMock()
        chunks = _make_tool_call_stream_chunks()
        model.client.completion = MagicMock(return_value=_mock_stream(chunks))

        results = list(model._stream([HumanMessage(content="hi")]))

        # Usage should still be recorded regardless of tool call presence
        events = get_pending_token_events()
        assert len(events) == 1
        usage = events[0]["usage"]
        assert usage["prompt_tokens"] == 20
        assert usage["total_tokens"] == 30

    def test_no_usage_when_provider_omits_usage(self):
        """Gracefully handles providers that don't return usage data."""
        model = ChatLiteLLM(model="openai/test-model")
        model.client = MagicMock()
        chunks = _make_stream_chunks(include_usage=False)
        model.client.completion = MagicMock(return_value=_mock_stream(chunks))

        results = list(model._stream([HumanMessage(content="hi")]))

        # Sentinel is still yielded
        last = results[-1]
        assert last.message.content == ""

        # But no token events (usage was None)
        events = get_pending_token_events()
        assert len(events) == 0


class TestAsyncStreamSentinel:
    """Tests for async _astream sentinel chunk behavior."""

    @pytest.mark.asyncio
    async def test_yields_sentinel_when_no_tool_call(self):
        """Sentinel chunk is yielded after finalize_stream when no tool call."""
        from unittest.mock import AsyncMock

        model = ChatLiteLLM(model="openai/test-model")
        model.client = MagicMock()
        chunks = _make_stream_chunks(include_usage=True)
        model.client.acreate = AsyncMock(return_value=_mock_astream(chunks))

        results = []
        async for chunk in model._astream([HumanMessage(content="hi")]):
            results.append(chunk)

        last = results[-1]
        assert isinstance(last, ChatGenerationChunk)
        assert last.message.content == ""
        assert isinstance(last.message, AIMessageChunk)

    @pytest.mark.asyncio
    async def test_token_usage_recorded_after_stream(self):
        """Token usage is correctly recorded via async path."""
        from unittest.mock import AsyncMock

        model = ChatLiteLLM(model="openai/test-model")
        model.client = MagicMock()
        chunks = _make_stream_chunks(include_usage=True)
        model.client.acreate = AsyncMock(return_value=_mock_astream(chunks))

        results = []
        async for chunk in model._astream([HumanMessage(content="hi")]):
            results.append(chunk)

        events = get_pending_token_events()
        assert len(events) == 1
        usage = events[0]["usage"]
        assert usage["prompt_tokens"] == 10
        assert usage["completion_tokens"] == 5
        assert usage["total_tokens"] == 15

    @pytest.mark.asyncio
    async def test_no_usage_when_provider_omits_usage(self):
        """Gracefully handles providers that don't return usage data (async)."""
        from unittest.mock import AsyncMock

        model = ChatLiteLLM(model="openai/test-model")
        model.client = MagicMock()
        chunks = _make_stream_chunks(include_usage=False)
        model.client.acreate = AsyncMock(return_value=_mock_astream(chunks))

        results = []
        async for chunk in model._astream([HumanMessage(content="hi")]):
            results.append(chunk)

        last = results[-1]
        assert last.message.content == ""
        events = get_pending_token_events()
        assert len(events) == 0
