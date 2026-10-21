"""Loopback fake LLM provider for wire-level adapter tests.

[INPUT]
- stdlib http.server / threading (POS: loopback HTTP server on a daemon thread)

[OUTPUT]
- FakeProviderServer: records every JSON request body and answers with a scripted reply
- FakeReply: status, content type and body of one scripted response
- openai_text_stream() / openai_tool_stream(): OpenAI chat-completions SSE bodies, finished or cut
- anthropic_text_stream() / anthropic_tool_stream(): Anthropic Messages SSE bodies, finished or cut
- strict_anthropic_responder(): Anthropic-style validation (unknown top-level field -> HTTP 400)

[POS]
Shared test double that lets a test drive the real adapter -> LiteLLM -> HTTP path offline: assert on the
request body that reaches the wire and on how finished or cut streams are handled.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import TracebackType
from typing import Any

JsonBody = dict[str, Any]


@dataclass(frozen=True)
class FakeReply:
    """One scripted HTTP response."""

    body: bytes
    status: int = 200
    content_type: str = "text/event-stream"


class FakeProviderServer:
    """Threaded loopback server that records request bodies and replies through ``respond``.

    HTTP/1.0 keeps the socket closing right after the body, which is how a gateway or proxy
    ends a stream it cut short: a clean close with no provider finish marker.
    """

    def __init__(self, respond: Callable[[JsonBody], FakeReply]) -> None:
        self.requests: list[JsonBody] = []
        requests = self.requests

        class _Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def do_POST(self) -> None:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                requests.append(body)
                reply = respond(body)
                self.send_response(reply.status)
                self.send_header("Content-Type", reply.content_type)
                self.send_header("Content-Length", str(len(reply.body)))
                self.end_headers()
                self.wfile.write(reply.body)

            def log_message(self, *_args: object) -> None:
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def __enter__(self) -> FakeProviderServer:
        self._thread.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


# --- OpenAI chat-completions streams ---------------------------------------------------------------------


def _openai_event(delta: JsonBody, finish: str | None = None) -> str:
    chunk = {
        "id": "chatcmpl-fake",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": "fake",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }
    return f"data: {json.dumps(chunk)}\n\n"


_OPENAI_DONE = "data: [DONE]\n\n"


def openai_text_stream(text: str = "ok", *, finish: str | None = "stop", send_done: bool = True) -> bytes:
    """Text answer. ``finish=None, send_done=False`` is a stream cut after the content."""
    events = [_openai_event({"role": "assistant", "content": text})]
    if finish is not None:
        events.append(_openai_event({}, finish))
    if send_done:
        events.append(_OPENAI_DONE)
    return "".join(events).encode()


def openai_tool_stream(
    name: str,
    argument_pieces: Iterable[str],
    *,
    finish: str | None = "tool_calls",
    send_done: bool = True,
) -> bytes:
    """One tool call whose arguments arrive in ``argument_pieces``.

    ``finish=None`` omits the provider finish marker; adding ``send_done=False`` as well
    models a connection cut in the middle of the call.
    """
    opening = _openai_event(
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"index": 0, "id": "call_1", "type": "function", "function": {"name": name, "arguments": ""}}
            ],
        }
    )
    pieces = [
        _openai_event({"tool_calls": [{"index": 0, "function": {"arguments": piece}}]}) for piece in argument_pieces
    ]
    tail = [_openai_event({}, finish)] if finish is not None else []
    if send_done:
        tail.append(_OPENAI_DONE)
    return "".join([opening, *pieces, *tail]).encode()


# --- Anthropic Messages streams --------------------------------------------------------------------------


def _anthropic_event(event: str, data: JsonBody) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n".encode()


_ANTHROPIC_START = _anthropic_event(
    "message_start",
    {
        "type": "message_start",
        "message": {
            "id": "msg_fake",
            "type": "message",
            "role": "assistant",
            "model": "claude-sonnet-4-20250514",
            "content": [],
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {"input_tokens": 3, "output_tokens": 1},
        },
    },
)
_ANTHROPIC_BLOCK_STOP = _anthropic_event("content_block_stop", {"type": "content_block_stop", "index": 0})


def _anthropic_finish(stop_reason: str) -> bytes:
    delta = {
        "type": "message_delta",
        "delta": {"stop_reason": stop_reason, "stop_sequence": None},
        "usage": {"output_tokens": 9},
    }
    return _anthropic_event("message_delta", delta) + _anthropic_event("message_stop", {"type": "message_stop"})


def anthropic_text_stream(text: str = "ok", *, stop_reason: str | None = "end_turn") -> bytes:
    """Text answer; ``stop_reason=None`` cuts the stream after the content block closed."""
    block = _anthropic_event(
        "content_block_start",
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
    )
    delta = _anthropic_event(
        "content_block_delta",
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}},
    )
    tail = _anthropic_finish(stop_reason) if stop_reason is not None else b""
    return _ANTHROPIC_START + block + delta + _ANTHROPIC_BLOCK_STOP + tail


def anthropic_tool_stream(
    name: str,
    argument_pieces: Iterable[str],
    *,
    stop_reason: str | None = "tool_use",
    close_block: bool = True,
) -> bytes:
    """One tool_use block whose JSON arrives in ``argument_pieces``.

    ``stop_reason=None`` drops the message_delta that carries the finish marker;
    ``close_block=False`` additionally cuts the stream before the block is closed.
    """
    opening = _anthropic_event(
        "content_block_start",
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "tool_use", "id": "toolu_fake", "name": name, "input": {}},
        },
    )
    pieces = [
        _anthropic_event(
            "content_block_delta",
            {"type": "content_block_delta", "index": 0, "delta": {"type": "input_json_delta", "partial_json": piece}},
        )
        for piece in argument_pieces
    ]
    tail = _anthropic_finish(stop_reason) if stop_reason is not None else b""
    return _ANTHROPIC_START + opening + b"".join(pieces) + (_ANTHROPIC_BLOCK_STOP if close_block else b"") + tail


# Top-level fields of the Anthropic Messages API request. The real API rejects anything else.
ANTHROPIC_REQUEST_FIELDS = frozenset(
    {
        "model",
        "messages",
        "max_tokens",
        "metadata",
        "stop_sequences",
        "stream",
        "system",
        "temperature",
        "tool_choice",
        "tools",
        "top_k",
        "top_p",
        "thinking",
        "service_tier",
        "container",
        "mcp_servers",
        "context_management",
        "output_config",
        "output_format",
    }
)


def strict_anthropic_responder(ok_stream: bytes) -> Callable[[JsonBody], FakeReply]:
    """Reply like the Messages API: HTTP 400 on the first unknown top-level field, else ``ok_stream``."""

    def respond(body: JsonBody) -> FakeReply:
        unknown = next((key for key in body if key not in ANTHROPIC_REQUEST_FIELDS), None)
        if unknown is None:
            return FakeReply(ok_stream)
        error = {
            "type": "error",
            "error": {"type": "invalid_request_error", "message": f"{unknown}: Extra inputs are not permitted"},
        }
        return FakeReply(json.dumps(error).encode(), status=400, content_type="application/json")

    return respond
