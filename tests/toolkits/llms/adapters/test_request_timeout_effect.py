"""``request_timeout`` bounds how long a provider call waits for the provider, on every wire protocol.

The tests talk to a real socket on loopback instead of a stub of the provider client: the property under test is
that the limit reaches the HTTP layer, which no assertion on the parameters handed to ``litellm`` can show (it
ignores some parameter names on some wires).
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import pytest
from langchain_core.messages import HumanMessage

from myrm_agent_harness.core.config.wire import WireProtocol
from myrm_agent_harness.toolkits.llms.adapters.chat_model.model import ChatLiteLLM
from myrm_agent_harness.toolkits.llms.errors.classifier import ErrorKind, classify_error

_REQUEST_TIMEOUT = 0.8
# A call that honours the timeout ends within a few multiples of it (the HTTP client may retry); one that does not
# is still waiting when this guard cuts the test.
_GUARD_SECONDS = 15.0
_ENDS_WITHIN_SECONDS = 10.0

_Handler = Callable[[asyncio.StreamReader, asyncio.StreamWriter], Awaitable[None]]


async def _read_request(reader: asyncio.StreamReader) -> None:
    await reader.readuntil(b"\r\n\r\n")


async def _never_answers(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        await _read_request(reader)
        await asyncio.sleep(3600)
    except (asyncio.CancelledError, ConnectionError, asyncio.IncompleteReadError):
        pass
    finally:
        writer.close()


def _completion(content: str) -> bytes:
    body = {
        "id": "cmpl-1",
        "object": "chat.completion",
        "created": 0,
        "model": "gpt-test",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }
    payload = json.dumps(body).encode()
    return b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: %d\r\n\r\n%s" % (
        len(payload),
        payload,
    )


async def _answers_after(delay: float, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        await _read_request(reader)
        await asyncio.sleep(delay)
        writer.write(_completion("late"))
        await writer.drain()
    except (asyncio.CancelledError, ConnectionError, asyncio.IncompleteReadError):
        pass
    finally:
        writer.close()


async def _streams_slowly(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """Answers at once, then produces a chunk every 0.25 s for 1.5 s: longer than the timeout, never silent for it."""

    def chunk(delta: dict[str, str], finish: str | None) -> bytes:
        event = {
            "id": "cmpl-1",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": "gpt-test",
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }
        data = b"data: " + json.dumps(event).encode() + b"\n\n"
        return b"%x\r\n%s\r\n" % (len(data), data)

    try:
        await _read_request(reader)
        writer.write(
            b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nTransfer-Encoding: chunked\r\n\r\n"
            + chunk({"role": "assistant", "content": ""}, None)
        )
        await writer.drain()
        for _ in range(6):
            await asyncio.sleep(0.25)
            writer.write(chunk({"content": "x"}, None))
            await writer.drain()
        done = b"data: [DONE]\n\n"
        writer.write(chunk({}, "stop") + b"%x\r\n%s\r\n0\r\n\r\n" % (len(done), done))
        await writer.drain()
    except (asyncio.CancelledError, ConnectionError, asyncio.IncompleteReadError):
        pass
    finally:
        writer.close()


@asynccontextmanager
async def _provider(handler: _Handler) -> AsyncIterator[str]:
    """Serve ``handler`` on loopback; leaving the block closes every connection a hung call left open."""
    writers: list[asyncio.StreamWriter] = []

    async def serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writers.append(writer)
        await handler(reader, writer)

    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}/v1"
    finally:
        server.close()
        for writer in writers:
            writer.close()
        await server.wait_closed()


def _model(api_base: str, wire: WireProtocol, *, streaming: bool) -> ChatLiteLLM:
    return ChatLiteLLM(
        model="claude-test" if wire == "anthropic_messages" else "openai/gpt-test",
        api_base=api_base,
        api_key="sk-test",
        request_timeout=_REQUEST_TIMEOUT,
        wire_protocol=wire,
        streaming=streaming,
        empty_retry_enabled=False,
    )


async def _call(llm: ChatLiteLLM, *, streaming: bool) -> str:
    messages = [HumanMessage(content="hi")]
    if not streaming:
        return str((await llm.ainvoke(messages)).content)
    return "".join([str(chunk.content) async for chunk in llm.astream(messages)])


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True], ids=["non_stream", "stream"])
@pytest.mark.parametrize("wire", ["chat_completions", "responses", "anthropic_messages"])
async def test_a_provider_that_never_answers_fails_as_a_timeout_within_the_request_timeout(
    wire: WireProtocol, streaming: bool
) -> None:
    async with _provider(_never_answers) as api_base:
        llm = _model(api_base, wire, streaming=streaming)
        started = time.monotonic()
        with pytest.raises(Exception) as caught:
            await asyncio.wait_for(_call(llm, streaming=streaming), _GUARD_SECONDS)
        elapsed = time.monotonic() - started

    assert elapsed < _ENDS_WITHIN_SECONDS, f"still waiting for the provider after {elapsed:.0f}s"
    assert classify_error(caught.value) == ErrorKind.TIMEOUT


@pytest.mark.asyncio
@pytest.mark.parametrize("wire", ["chat_completions", "responses", "anthropic_messages"])
async def test_a_synchronous_call_to_a_provider_that_never_answers_fails_as_a_timeout(wire: WireProtocol) -> None:
    async with _provider(_never_answers) as api_base:
        llm = _model(api_base, wire, streaming=False)
        started = time.monotonic()
        # The provider lives on this event loop, so the blocking call runs in a thread.
        with pytest.raises(Exception) as caught:
            await asyncio.wait_for(asyncio.to_thread(llm.invoke, [HumanMessage(content="hi")]), _GUARD_SECONDS)
        elapsed = time.monotonic() - started

    assert elapsed < _ENDS_WITHIN_SECONDS, f"still waiting for the provider after {elapsed:.0f}s"
    assert classify_error(caught.value) == ErrorKind.TIMEOUT


@pytest.mark.asyncio
async def test_a_response_that_arrives_later_than_the_request_timeout_is_a_timeout() -> None:
    async def slow(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await _answers_after(2.5, reader, writer)

    async with _provider(slow) as api_base:
        llm = _model(api_base, "chat_completions", streaming=False)
        started = time.monotonic()
        with pytest.raises(Exception) as caught:
            await asyncio.wait_for(_call(llm, streaming=False), _GUARD_SECONDS)
        elapsed = time.monotonic() - started

    assert elapsed < _ENDS_WITHIN_SECONDS
    assert classify_error(caught.value) == ErrorKind.TIMEOUT


@pytest.mark.asyncio
async def test_a_stream_that_keeps_producing_is_not_cut_by_the_request_timeout() -> None:
    async with _provider(_streams_slowly) as api_base:
        llm = _model(api_base, "chat_completions", streaming=True)
        started = time.monotonic()
        text = await asyncio.wait_for(_call(llm, streaming=True), _GUARD_SECONDS)
        elapsed = time.monotonic() - started

    assert text == "xxxxxx"
    assert elapsed > _REQUEST_TIMEOUT, "the stream must outlive the timeout for this test to prove anything"
