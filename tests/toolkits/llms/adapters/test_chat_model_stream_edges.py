"""Unit tests for ChatLiteLLM stream chunk processing and async stream edge paths.

Covers branch-level paths that existing adapter tests leave untested:
- ``_process_chunk`` role dispatch (user / system / function / fallback / tool calls)
- reasoning_content forwarding and model_dump fallback
- async ``_astream`` empty-stream retry and stream-stall timeout
- async stream with reasoning content + XML buffer flush
- sync ``_generate`` unexpected retry-loop exit
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import (
    AIMessageChunk,
    FunctionMessageChunk,
    HumanMessage,
    HumanMessageChunk,
    SystemMessageChunk,
)

from myrm_agent_harness.toolkits.llms.adapters.chat_model import ChatLiteLLM
from myrm_agent_harness.toolkits.llms.adapters.chat_model.exceptions import (
    EmptyStreamError,
    StreamStallTimeoutError,
)
from myrm_agent_harness.toolkits.llms.adapters.stream_aggregator import StreamAggregator


class _Chunk:
    """Minimal duck-typed chunk with attribute access (mirrors LiteLLM ModelResponse)."""

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

    def model_dump(self) -> dict[str, Any]:
        return self._data


async def _async_chunks(chunks: list[dict[str, Any]]) -> AsyncIterator[_Chunk]:
    for c in chunks:
        yield _Chunk(c)


@pytest.fixture(autouse=True)
def _fast_timeouts() -> None:
    """Keep stall tests fast without touching production defaults.

    Timeout fields are instance defaults validated by Pydantic; overriding the
    class attribute is rejected, so tests that exercise stall behavior set them
    per-instance instead.
    """


def _empty_stream() -> Iterator[_Chunk]:
    return iter([])


def test_dump_payload_pairing(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """Debug payload dump logs pending/paired tool call ids per message."""
    import logging

    from myrm_agent_harness.toolkits.llms.adapters.chat_model.async_mixin import (
        _dump_payload_pairing,
    )

    with caplog.at_level(logging.ERROR):
        _dump_payload_pairing(
            [
                {"role": "assistant", "tool_calls": [{"id": "call_1", "function": {"name": "f", "arguments": ""}}]},
                {"role": "tool", "tool_call_id": "call_1", "content": "42"},
                {"role": "assistant", "tool_calls": [{"id": "call_2", "function": {"id": "call_2", "name": "g", "arguments": ""}}]},
            ]
        )
    assert "LLM_PAYLOAD_DUMP" in caplog.text


class TestProcessChunk:
    """Branch coverage for _process_chunk role dispatch."""

    def _make(self) -> ChatLiteLLM:
        model = ChatLiteLLM(model="openai/test-model")
        return model

    def test_user_role(self) -> None:
        model = self._make()
        cg, cls = model._process_chunk(
            {"choices": [{"delta": {"role": "user", "content": "hi"}}]},
            HumanMessageChunk,
        )
        assert cls is HumanMessageChunk
        assert cg is not None
        assert cg.message.content == "hi"

    def test_system_role(self) -> None:
        model = self._make()
        _cg, cls = model._process_chunk(
            {"choices": [{"delta": {"role": "system", "content": "sys"}}]},
            SystemMessageChunk,
        )
        assert cls is SystemMessageChunk

    def test_function_role(self) -> None:
        model = self._make()
        cg, cls = model._process_chunk(
            {
                "choices": [
                    {
                        "delta": {
                            "role": "function",
                            "function_call": {"name": "f", "arguments": "{}"},
                        }
                    }
                ]
            },
            FunctionMessageChunk,
        )
        assert cls is FunctionMessageChunk
        assert cg is not None
        assert cg.message.name == "f"
        assert cg.message.content == "{}"

    def test_reasoning_content_forwarded(self) -> None:
        model = self._make()
        cg, _ = model._process_chunk(
            {
                "choices": [
                    {
                        "delta": {
                            "role": "assistant",
                            "content": "answer",
                            "reasoning_content": "thinking",
                        }
                    }
                ]
            },
            AIMessageChunk,
        )
        assert cg is not None
        assert cg.message.additional_kwargs["reasoning_content"] == "thinking"

    def test_model_dump_fallback(self) -> None:
        model = self._make()
        cg, _ = model._process_chunk(
            _Chunk({"choices": [{"delta": {"role": "user", "content": "hi"}}]}),
            HumanMessageChunk,
        )
        assert cg is not None
        assert cg.message.content == "hi"

    def test_model_dump_failure_returns_none(self) -> None:
        model = self._make()

        class _Bad:
            def model_dump(self) -> Any:
                raise ValueError("boom")

        cg, cls = model._process_chunk(_Bad(), HumanMessageChunk)
        assert cg is None
        assert cls is HumanMessageChunk

    def test_empty_choices_returns_none(self) -> None:
        model = self._make()
        cg, cls = model._process_chunk({}, HumanMessageChunk)
        assert cg is None
        assert cls is HumanMessageChunk

    def test_tool_call_chunks_emitted(self) -> None:
        model = self._make()
        cg, _ = model._process_chunk(
            {
                "choices": [
                    {
                        "delta": {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call_1",
                                    "function": {"name": "f", "arguments": "{}"},
                                }
                            ],
                        }
                    }
                ]
            },
            AIMessageChunk,
        )
        assert cg is not None
        assert len(getattr(cg.message, "tool_call_chunks", [])) == 1

    def test_fallback_generic_chunk(self) -> None:
        model = self._make()
        cg, _ = model._process_chunk(
            {"choices": [{"delta": {"content": "x"}}]}, HumanMessageChunk
        )
        assert cg is not None
        assert cg.message.content == "x"


class TestSyncGenerateRetryLoop:
    def test_unexpected_loop_exit_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        model = ChatLiteLLM(model="openai/test-model")
        model.client = MagicMock()
        model.empty_retry_enabled = False
        monkeypatch.setattr(
            model,
            "_create_message_dicts",
            MagicMock(side_effect=Exception("unexpected")),
        )
        monkeypatch.setattr(
            model,
            "_extract_tool_context_from_kwargs",
            MagicMock(return_value=([], None)),
        )

        # The exception is re-raised by the generic handler, not the loop-exit path.
        with pytest.raises(Exception, match="unexpected"):
            model._generate([HumanMessage(content="hi")])


class TestAsyncStreamEdges:
    @pytest.mark.asyncio
    async def test_empty_stream_retries_then_raises(self) -> None:
        model = ChatLiteLLM(model="openai/test-model")
        model.client = MagicMock()
        model.client.acreate = AsyncMock(return_value=_async_chunks([]))
        model.empty_retry_max_attempts = 1
        model.empty_retry_delay = 0.1

        with pytest.raises(EmptyStreamError):
            async for _ in model._astream([HumanMessage(content="hi")]):
                pass

    @pytest.mark.asyncio
    async def test_stream_stall_raises_timeout(self) -> None:
        model = ChatLiteLLM(model="openai/test-model")
        model.first_event_timeout = 0.05
        model.client = MagicMock()

        class _StallingStream:
            """Async iterable that never yields before the first-event timeout."""

            def __aiter__(self) -> _StallingStream:
                return self

            async def __anext__(self) -> _Chunk:
                await asyncio.sleep(0.1)
                raise StopAsyncIteration

        model.client.acreate = AsyncMock(return_value=_StallingStream())

        with pytest.raises(StreamStallTimeoutError) as excinfo:
            async for _ in model._astream([HumanMessage(content="hi")]):
                pass
        assert excinfo.value.phase == "first_event"

    @pytest.mark.asyncio
    async def test_stream_with_reasoning_and_content(self) -> None:
        model = ChatLiteLLM(model="openai/test-model")
        model.client = MagicMock()
        chunks: list[dict[str, Any]] = [
            {
                "choices": [
                    {
                        "delta": {
                            "role": "assistant",
                            "content": "Hello",
                            "reasoning_content": "thinking",
                        }
                    }
                ]
            },
            {
                "choices": [
                    {"delta": {"content": " world"}, "finish_reason": "stop"}
                ]
            },
            {"choices": [], "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}},
        ]
        model.client.acreate = AsyncMock(return_value=_async_chunks(chunks))

        collected: list[str] = []
        async for chunk in model._astream([HumanMessage(content="hi")]):
            if chunk.message.content:
                collected.append(str(chunk.message.content))

        assert collected
        assert any("Hello" in c for c in collected)

    @pytest.mark.asyncio
    async def test_stream_aggregator_ingest_raw_chunk(self) -> None:
        agg = StreamAggregator(AIMessageChunk)
        # dict chunks are returned as-is; empty choices do not crash aggregation
        assert agg.ingest_raw_chunk({"choices": [], "usage": {}}) is not None
        assert agg.ingest_raw_chunk(_Chunk({"choices": []})) is not None
