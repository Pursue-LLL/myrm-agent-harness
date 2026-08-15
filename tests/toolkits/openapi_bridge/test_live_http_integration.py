"""Live HTTP integration tests for openapi_bridge — real end-to-end wiring.

Boots a real local HTTP server exposing an OpenAPI 3.0 spec plus echo
endpoints, then drives the full production chain with zero mocks on the key
paths: ``parse_spec_from_url`` (real spec fetch) → ``generate_tools`` →
LLM-style string arguments → schema coercion → ``OpenAPIExecutor`` real HTTP
call → server-side type assertions.

Precision-critical cases mirror the MCP live coercion suite: big integers
(≥ 2^53) must reach the server as exact ints, never rounded through float().
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import urlparse

import pytest

from myrm_agent_harness.toolkits.openapi_bridge.config import OpenAPIServiceConfig
from myrm_agent_harness.toolkits.openapi_bridge.spec_parser import parse_spec_from_url
from myrm_agent_harness.toolkits.openapi_bridge.tool_generator import generate_tools

_SPEC = {
    "openapi": "3.0.3",
    "info": {"title": "Echo API", "version": "1.0"},
    "paths": {
        "/items/{item_id}": {
            "get": {
                "operationId": "getItem",
                "parameters": [
                    {
                        "name": "item_id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "integer"},
                    }
                ],
                "responses": {"200": {"description": "OK"}},
            }
        },
        "/items": {
            "post": {
                "operationId": "createItem",
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "integer"},
                                    "amount": {"type": "number"},
                                },
                                "required": ["id"],
                            }
                        }
                    }
                },
                "responses": {"201": {"description": "Created"}},
            }
        },
    },
}


class _EchoHandler(BaseHTTPRequestHandler):
    """Records what the server actually receives so tests can assert types."""

    received_path_params: list[str] = []
    received_bodies: list[dict[str, Any]] = []

    def log_message(self, format: str, *args: object) -> None:
        return

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/spec.json":
            self._send_json(_SPEC)
            return
        if path.startswith("/items/"):
            item_id = path.split("/items/", 1)[1]
            self.received_path_params.append(item_id)
            self._send_json({"received": item_id})
            return
        self._send_json({"error": "not found"}, status=404)

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/items":
            self._send_json({"error": "not found"}, status=404)
            return
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) or b"{}"
        payload = json.loads(raw)
        self.received_bodies.append(payload)
        self._send_json({"ok": True, "received": payload}, status=201)


class _EchoServer:
    """Thread-backed real HTTP server on an ephemeral port."""

    def __init__(self) -> None:
        self.base_url = ""
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    def __enter__(self) -> _EchoServer:
        _EchoHandler.received_path_params.clear()
        _EchoHandler.received_bodies.clear()
        self._server = HTTPServer(("127.0.0.1", 0), _EchoHandler)
        self.base_url = f"http://127.0.0.1:{self._server.server_address[1]}"
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True, name="test-openapi-echo-server"
        )
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None


@pytest.fixture
def _echo_url(monkeypatch: pytest.MonkeyPatch) -> str:
    """Live local OpenAPI server (ephemeral port), SSRF-shield allowlisted."""
    monkeypatch.setenv("MYRM_ALLOWED_INTERNAL_HOSTS", "127.0.0.1")
    with _EchoServer() as server:
        yield server.base_url


@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_spec_fetched_over_real_http(_echo_url: str) -> None:
    """parse_spec_from_url really fetches and parses the served spec."""
    spec = await parse_spec_from_url(f"{_echo_url}/spec.json")
    assert spec.title == "Echo API"
    assert [ep.operation_id for ep in spec.endpoints] == ["getItem", "createItem"]
    assert spec.base_url == ""  # spec declares no servers; config.base_url overrides


@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_big_integer_path_param_exact(_echo_url: str) -> None:
    """A 2^53-boundary path param reaches the server as the exact digit string."""
    config = OpenAPIServiceConfig(
        name="echo", spec_url=f"{_echo_url}/spec.json", base_url=_echo_url
    )
    tools = await generate_tools(config, await parse_spec_from_url(f"{_echo_url}/spec.json"))
    get_tool = next(t for t in tools if t.name == "echo_getItem")
    result = await get_tool.coroutine(item_id="9007199254740993")
    assert _EchoHandler.received_path_params == ["9007199254740993"]
    assert '"received": "9007199254740993"' in result


@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_big_integer_body_exact(_echo_url: str) -> None:
    """A 2^53-boundary integer body field arrives at the server as an exact int."""
    config = OpenAPIServiceConfig(
        name="echo", spec_url=f"{_echo_url}/spec.json", base_url=_echo_url
    )
    tools = await generate_tools(config, await parse_spec_from_url(f"{_echo_url}/spec.json"))
    create_tool = next(t for t in tools if t.name == "echo_createItem")
    await create_tool.coroutine(id="9007199254740993", amount="3.5")

    received = _EchoHandler.received_bodies[0]
    assert received["id"] == 9007199254740993
    assert isinstance(received["id"], int)
    assert isinstance(received["amount"], float)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_float_form_big_integer_body_lossless(_echo_url: str) -> None:
    """'9007199254740993.0' normalizes to the exact int, not a rounded float."""
    config = OpenAPIServiceConfig(
        name="echo", spec_url=f"{_echo_url}/spec.json", base_url=_echo_url
    )
    tools = await generate_tools(config, await parse_spec_from_url(f"{_echo_url}/spec.json"))
    create_tool = next(t for t in tools if t.name == "echo_createItem")
    await create_tool.coroutine(id="9007199254740993.0", amount="1")

    received = _EchoHandler.received_bodies[0]
    assert received["id"] == 9007199254740993
    assert isinstance(received["id"], int)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_number_body_coerced_to_float(_echo_url: str) -> None:
    """A decimal string for a number field arrives as a real float."""
    config = OpenAPIServiceConfig(
        name="echo", spec_url=f"{_echo_url}/spec.json", base_url=_echo_url
    )
    tools = await generate_tools(config, await parse_spec_from_url(f"{_echo_url}/spec.json"))
    create_tool = next(t for t in tools if t.name == "echo_createItem")
    await create_tool.coroutine(id="7", amount="3.14159")

    received = _EchoHandler.received_bodies[0]
    assert received["amount"] == 3.14159
    assert isinstance(received["amount"], float)
