"""Real uvicorn-hosted ASGI servers for live MCP transport tests.

[INPUT]
- uvicorn::Server (POS: real HTTP / HTTPS listener on a loopback socket the caller pre-binds and can observe)
- mcp.server.mcpserver::MCPServer (POS: real MCP protocol server exposing echo/add)
- tests.support.mcp_tls_pki::TlsPki (POS: server / CA certificate material for TLS and mTLS listeners)
- tests.support.sse_shutdown_flag::reset_sse_shutdown_flag (POS: per-server teardown)

[OUTPUT]
- LiveServer: running server handle (base_url + stop)
- HTTP_ENDPOINT_PATH: MCP endpoint path per HTTP transport
- start_live_server: boot any ASGI app on a pre-bound loopback port, optionally over TLS / mTLS
- build_probe_mcp_server: MCPServer exposing the echo and add tools (optionally with initialize instructions)
- serve_probe_mcp: serve the probe MCP server over one HTTP transport and yield its endpoint URL
- error_chain_text: flatten an exception tree into lowercase searchable text

[POS]
Harness pytest-only helper shared by every live transport test, so the server bootstrap
(pre-bound socket, readiness poll, shutdown-flag reset) exists exactly once.
"""

from __future__ import annotations

import asyncio
import socket
import ssl
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass

import uvicorn
from mcp.server.mcpserver import MCPServer
from starlette.types import ASGIApp

from tests.support.mcp_tls_pki import TlsPki
from tests.support.sse_shutdown_flag import reset_sse_shutdown_flag

HTTP_ENDPOINT_PATH = {"streamable_http": "/mcp", "sse": "/sse"}

_START_POLL_ATTEMPTS = 200
_START_POLL_INTERVAL_SEC = 0.05


@dataclass(slots=True)
class LiveServer:
    """A running loopback server; ``base_url`` has no trailing slash."""

    base_url: str
    _runner: uvicorn.Server
    _serve_task: asyncio.Task[None]

    async def stop(self) -> None:
        self._runner.should_exit = True
        with suppress(Exception):
            await self._serve_task
        await reset_sse_shutdown_flag()


def build_probe_mcp_server(name: str = "transport-probe", *, instructions: str | None = None) -> MCPServer:
    """A minimal real MCP server exposing ``echo`` and ``add``."""
    server = MCPServer(name, instructions=instructions)

    @server.tool()
    def echo(text: str) -> str:
        return f"echo:{text}"

    @server.tool()
    def add(a: int, b: int) -> int:
        return a + b

    return server


async def start_live_server(
    app: ASGIApp,
    *,
    tls: TlsPki | None = None,
    require_client_cert: bool = False,
) -> LiveServer:
    """Serve *app* on a pre-bound 127.0.0.1 port; HTTPS when *tls* is given, mTLS when a client cert is required."""
    if require_client_cert and tls is None:
        raise ValueError("require_client_cert needs a TlsPki")

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]

    tls_kwargs: dict[str, str | int] = {}
    if tls is not None:
        tls_kwargs = {"ssl_keyfile": str(tls.server_key), "ssl_certfile": str(tls.server_cert)}
        if require_client_cert:
            tls_kwargs |= {"ssl_ca_certs": str(tls.ca_cert), "ssl_cert_reqs": ssl.CERT_REQUIRED}

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", ws="none", **tls_kwargs)
    runner = uvicorn.Server(config)
    serve_task = asyncio.create_task(runner.serve(sockets=[sock]))
    server = LiveServer(
        base_url=f"{'https' if tls is not None else 'http'}://127.0.0.1:{port}",
        _runner=runner,
        _serve_task=serve_task,
    )
    for _ in range(_START_POLL_ATTEMPTS):
        if runner.started:
            return server
        await asyncio.sleep(_START_POLL_INTERVAL_SEC)
    await server.stop()
    raise RuntimeError(f"live server failed to start on port {port}")


@asynccontextmanager
async def serve_probe_mcp(
    transport: str,
    *,
    tls: TlsPki | None = None,
    require_client_cert: bool = False,
    instructions: str | None = None,
) -> AsyncIterator[str]:
    """Serve the probe MCP server over *transport* (``streamable_http`` or ``sse``) and yield its endpoint URL."""
    server = build_probe_mcp_server(instructions=instructions)
    app = server.sse_app() if transport == "sse" else server.streamable_http_app()
    live = await start_live_server(app, tls=tls, require_client_cert=require_client_cert)
    try:
        yield f"{live.base_url}{HTTP_ENDPOINT_PATH[transport]}"
    finally:
        await live.stop()


def error_chain_text(exc: BaseException) -> str:
    """Flatten an exception (causes, contexts and ExceptionGroup members) into lowercase searchable text."""
    seen: set[int] = set()
    parts: list[str] = []
    stack: list[BaseException] = [exc]
    while stack:
        current = stack.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        parts.append(f"{type(current).__name__}: {current}")
        if isinstance(current, BaseExceptionGroup):
            stack.extend(current.exceptions)
        stack.extend(linked for linked in (current.__cause__, current.__context__) if linked is not None)
    return "\n".join(parts).lower()
