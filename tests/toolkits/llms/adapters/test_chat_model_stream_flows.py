"""Unit tests for full-stream integration paths of ChatLiteLLM mixins.

Covers end-to-end streaming flows that unit-level chunk tests cannot reach:
- sync ``_stream`` with reasoning content, tool calls and a run_manager
- async ``_agenerate`` streaming path via ``agenerate_from_stream``
- empty-stream retry that succeeds on the second attempt
- provider failure and context-overflow fast-fail paths in retry loops
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import HumanMessage
from langchain_core.outputs import ChatGenerationChunk
from langchain_core.outputs.chat_result import ChatResult

from myrm_agent_harness.toolkits.llms.adapters.chat_model import ChatLiteLLM
from myrm_agent_harness.toolkits.llms.errors.classifier import (
    is_context_overflow,
)


class _Chunk:
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


def _stream_chunks() -> list[dict[str, Any]]:
    return [
        {
            "choices": [
                {
                    "delta": {
                        "role": "assistant",
                        "content": "Hello",
                        "reasoning_content": "reason",
                    }
                }
            ]
        },
        {
            "choices": [
                {
                    "delta": {
                        "content": " world",
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
        {
            "choices": [{"delta": {"content": None}, "finish_reason": "tool_calls"}]
        },
        {
            "choices": [],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        },
    ]


def _sync_iter(chunks: list[dict[str, Any]]) -> Iterator[_Chunk]:
    return iter([_Chunk(c) for c in chunks])


async def _async_iter(chunks: list[dict[str, Any]]) -> AsyncIterator[_Chunk]:
    for c in chunks:
        yield _Chunk(c)


class _SyncRunManager:
    """Recording run_manager for the sync ``_stream`` path (duck-typed)."""

    def __init__(self) -> None:
        self.tokens: list[str] = []

    def on_llm_new_token(
        self,
        token: str,
        *,
        chunk: ChatGenerationChunk | None = None,
        **kwargs: Any,
    ) -> Any:
        self.tokens.append(token)
        return None


class _AsyncRunManager:
    """Recording run_manager for the async ``_astream`` path (awaited call)."""

    def __init__(self) -> None:
        self.tokens: list[str] = []

    async def on_llm_new_token(
        self,
        token: str,
        *,
        chunk: ChatGenerationChunk | None = None,
        **kwargs: Any,
    ) -> Any:
        self.tokens.append(token)
        return None


class TestAsyncStreamRetryAndFlush:
    @pytest.mark.asyncio
    async def test_async_empty_stream_retry_succeeds(self) -> None:
        model = ChatLiteLLM(model="openai/test-model")
        model.client = MagicMock()
        calls = {"count": 0}

        async def _flaky(messages: Any, **kwargs: Any) -> Any:
            calls["count"] += 1
            if calls["count"] == 1:
                return _async_iter([])
            return _async_iter(_stream_chunks())

        model.client.acreate = AsyncMock(side_effect=_flaky)
        model.empty_retry_max_attempts = 2
        model.empty_retry_delay = 0.05

        results = []
        async for chunk in model._astream([HumanMessage(content="hi")]):
            results.append(chunk)
        assert len(results) >= 1
        assert calls["count"] == 2

    @pytest.mark.asyncio
    async def test_async_stream_flush_reasoning_buffer(self) -> None:
        """DSML reasoning flushed after stream end is yielded as a final chunk."""
        model = ChatLiteLLM(model="openai/test-model")
        model.client = MagicMock()
        # content is empty on every delta; only reasoning accumulates in the buffer
        chunks: list[dict[str, Any]] = [
            {
                "choices": [
                    {
                        "delta": {
                            "role": "assistant",
                            "content": None,
                            "reasoning_content": "think <reasoning>deep</reasoning>",
                        }
                    }
                ]
            },
            {"choices": [{"delta": {"content": None}, "finish_reason": "stop"}]},
        ]
        model.client.acreate = AsyncMock(return_value=_async_iter(chunks))

        collected = []
        async for chunk in model._astream([HumanMessage(content="hi")]):
            collected.append(chunk)
        assert len(collected) >= 1


class TestSyncFullStream:
    def test_stream_with_reasoning_tool_call_and_manager(self) -> None:
        model = ChatLiteLLM(model="openai/test-model")
        model.client = MagicMock()
        model.client.completion = MagicMock(
            return_value=_sync_iter(_stream_chunks())
        )
        manager = _SyncRunManager()

        results = list(
            model._stream([HumanMessage(content="hi")], run_manager=manager)
        )

        # tool-call chunk + content + sentinel are all yielded
        assert any(
            getattr(getattr(r.message, "tool_call_chunks", []), "__len__", lambda: 0)()
            for r in results
        )
        assert len(results) >= 2

    def test_empty_stream_retry_succeeds(self) -> None:
        model = ChatLiteLLM(model="openai/test-model")
        model.client = MagicMock()
        calls = {
            "count": 0,
        }

        def _flaky(messages: Any, **kwargs: Any) -> Iterator[_Chunk]:
            calls["count"] += 1
            if calls["count"] == 1:
                return iter([])
            return _sync_iter(_stream_chunks())

        model.client.completion = MagicMock(side_effect=_flaky)
        model.empty_retry_max_attempts = 2
        model.empty_retry_delay = 0.05

        results = list(model._stream([HumanMessage(content="hi")]))
        assert len(results) >= 1
        assert calls["count"] == 2

    def test_stream_flush_reasoning_only_at_end(self) -> None:
        """DSML reasoning buffered to stream end is flushed as a final chunk."""
        model = ChatLiteLLM(model="openai/test-model")
        model.client = MagicMock()
        # content stays empty; reasoning accumulates until flush
        chunks: list[dict[str, Any]] = [
            {
                "choices": [
                    {
                        "delta": {
                            "role": "assistant",
                            "content": None,
                            "reasoning_content": "<reasoning>deep</reasoning>",
                        }
                    }
                ]
            },
            {"choices": [{"delta": {"content": None}, "finish_reason": "stop"}]},
        ]
        model.client.completion = MagicMock(return_value=_sync_iter(chunks))

        results = list(model._stream([HumanMessage(content="hi")]))
        assert len(results) >= 1
        flushed = next(
            (
                r
                for r in results
                if getattr(r.message, "additional_kwargs", {}).get("reasoning_content")
            ),
            None,
        )
        assert flushed is not None


class TestAsyncAgenerateStreaming:
    @pytest.mark.asyncio
    async def test_agenerate_streaming_aggregates(self) -> None:
        model = ChatLiteLLM(model="openai/test-model")
        model.streaming = True
        model.client = MagicMock()
        model.client.acreate = AsyncMock(return_value=_async_iter(_stream_chunks()))

        result: ChatResult = await model._agenerate([HumanMessage(content="hi")])

        assert result.generations
        content = result.generations[0].message.content
        assert "Hello" in str(content)

    @pytest.mark.asyncio
    async def test_agenerate_provider_failure_raises(self) -> None:
        model = ChatLiteLLM(model="openai/test-model")
        model.streaming = False
        model.client = MagicMock()

        async def _boom(messages: Any, **kwargs: Any) -> Any:
            raise RuntimeError("provider down")

        model.client.acreate = AsyncMock(side_effect=_boom)

        with pytest.raises(RuntimeError, match="provider down"):
            await model._agenerate([HumanMessage(content="hi")])

    @pytest.mark.asyncio
    async def test_agenerate_streaming_fallback_on_type_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """agenerate_from_stream NoneType bug falls back to non-streaming."""
        import myrm_agent_harness.toolkits.llms.adapters.chat_model.async_mixin as mod

        model = ChatLiteLLM(model="openai/test-model")
        model.client = MagicMock()

        async def _boom_agenerate(
            messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any
        ) -> ChatResult:
            return ChatResult(generations=[])

        monkeypatch.setattr(
            mod,
            "agenerate_from_stream",
            MagicMock(
                side_effect=TypeError("'NoneType' object is not iterable")
            ),
        )
        monkeypatch.setattr(model, "_agenerate", _boom_agenerate)

        result = await model._agenerate_inner(
            [HumanMessage(content="hi")], streaming=True
        )
        assert isinstance(result, ChatResult)

    @pytest.mark.asyncio
    async def test_agenerate_streaming_generic_error_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Non-TypeError streaming failures propagate unchanged."""
        import myrm_agent_harness.toolkits.llms.adapters.chat_model.async_mixin as mod

        model = ChatLiteLLM(model="openai/test-model")
        model.client = MagicMock()

        async def _stream_bug(messages: Any, **kwargs: Any) -> Any:
            raise RuntimeError("stream exploded")

        async def _agg_from_stream(stream_iter: Any) -> Any:
            await stream_iter
            raise RuntimeError("stream exploded")

        monkeypatch.setattr(model, "_astream", _stream_bug)
        monkeypatch.setattr(mod, "agenerate_from_stream", _agg_from_stream)

        with pytest.raises(RuntimeError, match="stream exploded"):
            await model._agenerate_inner(
                [HumanMessage(content="hi")], streaming=True
            )

    @pytest.mark.asyncio
    async def test_async_stream_context_overflow_fast_fails(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        model = ChatLiteLLM(model="openai/test-model")
        model.client = MagicMock()

        async def _boom(messages: Any, **kwargs: Any) -> Any:
            raise ValueError("context length exceeded")

        model.client.acreate = AsyncMock(side_effect=_boom)
        model.empty_retry_enabled = False

        import myrm_agent_harness.toolkits.llms.errors.classifier as cls

        monkeypatch.setattr(cls, "is_context_overflow", lambda e: True)
        monkeypatch.setattr(
            cls, "parse_available_output_tokens_from_error", lambda e: None
        )

        with pytest.raises(ValueError, match="context length"):
            async for _ in model._astream([HumanMessage(content="hi")]):
                pass

    @pytest.mark.asyncio
    async def test_async_stream_tool_call_yields_final_chunk(self) -> None:
        """Streamed tool calls are recovered and yielded as the final chunk."""
        model = ChatLiteLLM(model="openai/test-model")
        model.client = MagicMock()
        chunks: list[dict[str, Any]] = [
            {
                "choices": [
                    {
                        "delta": {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call_1",
                                    "function": {"name": "f", "arguments": ""},
                                }
                            ],
                        }
                    }
                ]
            },
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {"index": 0, "function": {"arguments": "{}"}}
                            ]
                        }
                    }
                ]
            },
            {
                "choices": [{"delta": {"content": None}, "finish_reason": "tool_calls"}]
            },
        ]
        model.client.acreate = AsyncMock(return_value=_async_iter(chunks))

        collected = []
        async for chunk in model._astream([HumanMessage(content="hi")]):
            collected.append(chunk)
        # tool calls are aggregated into a single final chunk; verify recovery
        assert len(collected) >= 1
        last = collected[-1]
        assert getattr(last.message, "tool_calls", [])

    @pytest.mark.asyncio
    async def test_async_stream_with_run_manager(self) -> None:
        model = ChatLiteLLM(model="openai/test-model")
        model.client = MagicMock()
        chunks: list[dict[str, Any]] = [
            {"choices": [{"delta": {"role": "assistant", "content": "hi"}}]},
            {
                "choices": [
                    {"delta": {"content": None}, "finish_reason": "stop"}
                ]
            },
        ]
        model.client.acreate = AsyncMock(return_value=_async_iter(chunks))
        manager = _AsyncRunManager()

        async for _ in model._astream(
            [HumanMessage(content="hi")], run_manager=manager
        ):
            pass
        assert len(manager.tokens) >= 1

    @pytest.mark.asyncio
    async def test_agenerate_streaming_non_none_type_error_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TypeError without the NoneType marker is not treated as fallback."""
        import myrm_agent_harness.toolkits.llms.adapters.chat_model.async_mixin as mod

        model = ChatLiteLLM(model="openai/test-model")
        model.client = MagicMock()
        monkeypatch.setattr(
            mod,
            "agenerate_from_stream",
            MagicMock(side_effect=TypeError("unrelated type problem")),
        )

        with pytest.raises(TypeError, match="unrelated"):
            await model._agenerate_inner(
                [HumanMessage(content="hi")], streaming=True
            )

    @pytest.mark.asyncio
    async def test_async_stream_context_overflow_injects_max_tokens(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Context overflow with available tokens retries with injected max_tokens."""
        model = ChatLiteLLM(model="openai/test-model")
        model.client = MagicMock()
        calls = {"count": 0}

        async def _flaky(messages: Any, **kwargs: Any) -> Any:
            calls["count"] += 1
            if calls["count"] == 1:
                raise ValueError("context length exceeded, need 800 more")
            return _async_iter(
                [
                    {"choices": [{"delta": {"role": "assistant", "content": "ok"}}]},
                    {
                        "choices": [
                            {"delta": {"content": None}, "finish_reason": "stop"}
                        ]
                    },
                ]
            )

        model.client.acreate = AsyncMock(side_effect=_flaky)
        model.empty_retry_max_attempts = 2
        model.empty_retry_delay = 0.05

        import myrm_agent_harness.toolkits.llms.errors.classifier as cls

        monkeypatch.setattr(cls, "is_context_overflow", lambda e: True)
        monkeypatch.setattr(
            cls, "parse_available_output_tokens_from_error", lambda e: 800
        )

        collected = []
        async for chunk in model._astream([HumanMessage(content="hi")]):
            collected.append(chunk)
        assert calls["count"] == 2
        assert any("ok" in str(c.message.content) for c in collected)


class TestContextOverflowFastFail:
    def test_sync_context_overflow_fast_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        model = ChatLiteLLM(model="openai/test-model")
        model.client = MagicMock()

        def _boom(messages: Any, **kwargs: Any) -> Any:
            raise ValueError("context length exceeded, max output tokens")

        model.client.completion = MagicMock(side_effect=_boom)
        model.empty_retry_enabled = False
        model.max_retries = 0

        # is_context_overflow is imported lazily inside _generate; monkeypatch its
        # module attribute directly.
        import myrm_agent_harness.toolkits.llms.errors.classifier as cls

        monkeypatch.setattr(cls, "is_context_overflow", lambda e: True)
        monkeypatch.setattr(
            cls, "parse_available_output_tokens_from_error", lambda e: None
        )

        with pytest.raises(ValueError, match="context length"):
            model._generate([HumanMessage(content="hi")])

    def test_context_overflow_classifier_regex(self) -> None:
        assert is_context_overflow(ValueError("prompt is too long"))
        assert is_context_overflow(
            ValueError("This model's maximum context length is 128000")
        )
        assert not is_context_overflow(ValueError("rate limit"))
