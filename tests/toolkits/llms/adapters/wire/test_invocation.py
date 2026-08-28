"""Tests for Responses wire invocation error propagation."""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.llms.adapters.wire.invocation import (
    invoke_responses_sync,
    stream_responses_sync,
)
from myrm_agent_harness.toolkits.llms.adapters.wire.normalizer import ResponsesStreamError


class _FakeResponsesStream:
    def __init__(self, events: list[dict[str, object]]) -> None:
        self._events = events

    def __iter__(self):
        return iter(self._events)


class _StreamResponsesClient:
    def __init__(self, events: list[dict[str, object]]) -> None:
        self._events = events

    def responses(self, **_kwargs: object) -> _FakeResponsesStream:
        return _FakeResponsesStream(self._events)


class _FailOpenInvokeClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def responses(self, **_kwargs: object) -> dict[str, object]:
        self.calls.append(dict(_kwargs))
        if len(self.calls) == 1:
            raise RuntimeError("invalid_encrypted_content: stale blob")
        return {
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "ok"}],
                }
            ]
        }


def test_invoke_responses_sync_fail_open_on_invalid_encrypted_content() -> None:
    client = _FailOpenInvokeClient()
    messages = [
        {
            "role": "assistant",
            "content": "prior",
            "responses_reasoning_items": [{"type": "reasoning", "encrypted_content": "stale"}],
        }
    ]
    params = {"extra_body": {"include": ["reasoning.encrypted_content"]}}
    result = invoke_responses_sync(client, messages, params)
    assert len(client.calls) == 2
    assert "include" not in client.calls[1]
    assert result["choices"][0]["message"]["content"] == "ok"


def test_stream_responses_sync_raises_on_failed_event() -> None:
    client = _StreamResponsesClient(
        [{"type": "response.failed", "error": {"message": "Training not allowed for contributor"}}],
    )
    with pytest.raises(ResponsesStreamError, match="Training not allowed"):
        list(stream_responses_sync(client, [], {}))


def test_stream_responses_sync_yields_normal_chunks() -> None:
    client = _StreamResponsesClient(
        [{"type": "response.output_text.delta", "delta": "hi"}],
    )
    chunks = list(stream_responses_sync(client, [], {}))
    assert len(chunks) == 1
    assert chunks[0]["choices"][0]["delta"]["content"] == "hi"


class _FailOpenStreamClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def responses(self, **_kwargs: object) -> _FakeResponsesStream:
        self.calls.append(dict(_kwargs))
        if len(self.calls) == 1:
            raise RuntimeError("invalid_encrypted_content: stale blob")
        return _FakeResponsesStream([{"type": "response.output_text.delta", "delta": "retry-ok"}])


def test_stream_responses_sync_fail_open_on_invalid_encrypted_content() -> None:
    client = _FailOpenStreamClient()
    messages = [
        {
            "role": "assistant",
            "content": "prior",
            "responses_reasoning_items": [{"type": "reasoning", "encrypted_content": "stale"}],
        }
    ]
    params = {"extra_body": {"include": ["reasoning.encrypted_content"]}}
    chunks = list(stream_responses_sync(client, messages, params))
    assert len(client.calls) == 2
    assert "include" not in client.calls[1]
    assert chunks[0]["choices"][0]["delta"]["content"] == "retry-ok"


class _ModelDumpEvent:
    def model_dump(self) -> dict[str, object]:
        return {"type": "response.output_text.delta", "delta": "from-model-dump"}


def test_stream_responses_sync_accepts_model_dump_events() -> None:
    client = _StreamResponsesClient([_ModelDumpEvent()])
    chunks = list(stream_responses_sync(client, [], {}))
    assert chunks[0]["choices"][0]["delta"]["content"] == "from-model-dump"


class _AsyncFailOpenClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def aresponses(self, **_kwargs: object) -> dict[str, object]:
        self.calls.append(dict(_kwargs))
        if len(self.calls) == 1:
            raise RuntimeError("invalid_encrypted_content: stale blob")
        return {
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "async-ok"}],
                }
            ]
        }


@pytest.mark.asyncio
async def test_invoke_responses_async_fail_open_on_invalid_encrypted_content() -> None:
    from myrm_agent_harness.toolkits.llms.adapters.wire.invocation import invoke_responses_async

    client = _AsyncFailOpenClient()
    messages = [
        {
            "role": "assistant",
            "content": "prior",
            "responses_reasoning_items": [{"type": "reasoning", "encrypted_content": "stale"}],
        }
    ]
    params = {"extra_body": {"include": ["reasoning.encrypted_content"]}}
    result = await invoke_responses_async(client, messages, params)
    assert len(client.calls) == 2
    assert "include" not in client.calls[1]
    assert result["choices"][0]["message"]["content"] == "async-ok"


class _AsyncStreamClient:
    def __init__(self, events: list[object]) -> None:
        self._events = events

    async def aresponses(self, **_kwargs: object) -> _AsyncEventStream:
        return _AsyncEventStream(self._events)


class _AsyncEventStream:
    def __init__(self, events: list[object]) -> None:
        self._events = events

    def __aiter__(self) -> _AsyncEventStream:
        return self

    async def __anext__(self) -> object:
        if not self._events:
            raise StopAsyncIteration
        return self._events.pop(0)


@pytest.mark.asyncio
async def test_stream_responses_async_yields_chunks() -> None:
    from myrm_agent_harness.toolkits.llms.adapters.wire.invocation import stream_responses_async

    client = _AsyncStreamClient([{"type": "response.output_text.delta", "delta": "async-stream"}])
    chunks = [chunk async for chunk in stream_responses_async(client, [], {})]
    assert len(chunks) == 1
    assert chunks[0]["choices"][0]["delta"]["content"] == "async-stream"


class _LegacyDictEvent:
    def dict(self) -> dict[str, object]:
        return {"type": "response.output_text.delta", "delta": "legacy-dict"}


class _AttrEvent:
    type = "response.output_text.delta"
    delta = "attr-delta"
    response = None
    error = None


def test_stream_responses_sync_supports_legacy_dict_events() -> None:
    client = _StreamResponsesClient([_LegacyDictEvent()])
    chunks = list(stream_responses_sync(client, [], {}))
    assert chunks[0]["choices"][0]["delta"]["content"] == "legacy-dict"


def test_stream_responses_sync_supports_attribute_events() -> None:
    client = _StreamResponsesClient([_AttrEvent()])
    chunks = list(stream_responses_sync(client, [], {}))
    assert chunks[0]["choices"][0]["delta"]["content"] == "attr-delta"


def test_invoke_responses_sync_reraises_unrelated_errors() -> None:
    class _BoomClient:
        def responses(self, **_kwargs: object) -> dict[str, object]:
            raise RuntimeError("network down")

    with pytest.raises(RuntimeError, match="network down"):
        invoke_responses_sync(_BoomClient(), [], {})


class _AsyncFailOpenStreamClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def aresponses(self, **_kwargs: object) -> _AsyncEventStream:
        self.calls.append(dict(_kwargs))
        if len(self.calls) == 1:
            raise RuntimeError("invalid_encrypted_content: stale blob")
        return _AsyncEventStream([{"type": "response.output_text.delta", "delta": "async-retry"}])


@pytest.mark.asyncio
async def test_stream_responses_async_fail_open_on_invalid_encrypted_content() -> None:
    from myrm_agent_harness.toolkits.llms.adapters.wire.invocation import stream_responses_async

    client = _AsyncFailOpenStreamClient()
    params = {"extra_body": {"include": ["reasoning.encrypted_content"]}}
    chunks = [chunk async for chunk in stream_responses_async(client, [{"role": "user", "content": "hi"}], params)]
    assert len(client.calls) == 2
    assert "include" not in client.calls[1]
    assert chunks[0]["choices"][0]["delta"]["content"] == "async-retry"
