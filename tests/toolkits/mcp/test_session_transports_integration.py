"""Real-transport end-to-end regression for ``MCPSessionActor``.

Unlike the unit tests (which stub ``mcp.client.Client``), these spin up a *real*
MCP server and drive the production actor/connection-pool stack over actual
wire transports:

- streamable HTTP: a real uvicorn-hosted ``MCPServer`` on a pre-bound loopback
  socket, exercised through the production ``MCPConnectionManager``;
- stdio: a real ``MCPServer`` subprocess, the same path the existing
  session-reuse tests cover, here extended with the full actor lifecycle.

They also lock in the ``_http_client`` lifecycle guarantee: a headered
streamable-http transport must close its ``httpx2.AsyncClient`` on *every*
exit path — including the path where building the transport target raises
after the HTTP client was already allocated (so it never reaches the inner
``finally`` of the serve block).
"""

from __future__ import annotations

import asyncio
import socket
import sys
from contextlib import suppress

import pytest

from myrm_agent_harness.toolkits.mcp.config import MCPConfig
from myrm_agent_harness.toolkits.mcp.connection_manager import MCPConnectionManager
from myrm_agent_harness.toolkits.mcp.session_actor import MCPSessionActor

# A minimal real MCP server exposing echo/add over the requested transport.
_PROBE_SERVER_SRC = """
import sys

from mcp.server import MCPServer

server = MCPServer("transport-probe")


@server.tool()
def echo(text: str) -> str:
    return f"echo:{text}"


@server.tool()
def add(a: int, b: int) -> int:
    return a + b


if __name__ == "__main__":
    server.run(transport="stdio")
"""


@pytest.fixture
def _reset_manager() -> object:
    MCPConnectionManager._instance = None
    yield
    MCPConnectionManager._instance = None


async def _start_http_server() -> tuple[object, str]:
    """Boot a real streamable-http MCP server on a pre-bound loopback port.

    Returns an awaitable teardown plus the reachable URL. The socket is bound
    by the caller so uvicorn never needs to pick a port we cannot observe.
    """
    import uvicorn
    from mcp.server import MCPServer

    server = MCPServer("transport-probe")

    @server.tool()
    def echo(text: str) -> str:
        return f"echo:{text}"

    @server.tool()
    def add(a: int, b: int) -> int:
        return a + b

    app = server.streamable_http_app()

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    runner = uvicorn.Server(config)
    serve_task = asyncio.create_task(runner.serve(sockets=[sock]))
    for _ in range(200):
        if runner.started:
            break
        await asyncio.sleep(0.05)
    assert runner.started, "streamable-http server failed to start"

    async def teardown() -> None:
        runner.should_exit = True
        with suppress(Exception):
            await serve_task

    return teardown, f"http://127.0.0.1:{port}/mcp"


@pytest.mark.asyncio
async def test_streamable_http_real_server_full_lifecycle(
    _reset_manager: object
) -> None:
    """A real streamable-http server served end-to-end through the pool.

    Covers initialize -> list_tools -> call_tool over an actual HTTP wire
    transport.
    """
    teardown, url = await _start_http_server()
    try:
        cfg = MCPConfig(
            name="httpprobe",
            type="streamable_http",
            url=url,
            description="http probe",
            connect_timeout=30.0,
        )
        manager = await MCPConnectionManager.get_instance()
        try:
            conn = await manager.get_connection([cfg])
            assert "echo:hello" in str(await conn.call("httpprobe", "echo", {"text": "hello"}))
            assert "5" in str(await conn.call("httpprobe", "add", {"a": 2, "b": 3}))
        finally:
            await manager.stop()
    finally:
        await teardown()


@pytest.mark.asyncio
async def test_stdio_real_server_full_lifecycle(tmp_path, _reset_manager: object) -> None:
    """A real stdio server served through the pool (full lifecycle).

    Extends the existing session-reuse proof with list_tools + call_tool
    coverage across a real subprocess boundary.
    """
    script = tmp_path / "probe_server.py"
    script.write_text(_PROBE_SERVER_SRC, encoding="utf-8")

    cfg = MCPConfig(
        name="stdioprobe",
        type="stdio",
        command=sys.executable,
        args=[str(script)],
        description="stdio probe",
        connect_timeout=30.0,
    )
    manager = await MCPConnectionManager.get_instance()
    try:
        conn = await manager.get_connection([cfg])
        assert "echo:hi" in str(await conn.call("stdioprobe", "echo", {"text": "hi"}))
        assert "7" in str(await conn.call("stdioprobe", "add", {"a": 3, "b": 4}))
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_http_client_closed_when_target_build_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: a transport-target build failure must not leak ``_http_client``.

    ``_build_client_target`` allocates the ``httpx2.AsyncClient`` *before* it
    builds the SDK transport target. If building that target raises (e.g. an
    SDK validation error after the client was allocated), the inner ``finally``
    of the serve block never runs — only the loop-top and terminal-path
    cleanups release the transport client. We force that by allocating the
    client and then making the SDK import + target construction raise.
    """
    import httpx2

    real_build = MCPSessionActor._build_client_target

    def exploding_build(self, conn: dict[str, object]) -> object:
        headers: dict[str, str] = dict(conn.get("headers") or {})  # type: ignore[arg-type]
        # Same allocation as the production path: the client is created first...
        self._http_client = httpx2.AsyncClient(
            headers=headers,
            timeout=httpx2.Timeout(30.0, read=300.0),
            follow_redirects=True,
        )
        # ...then target construction fails before the serve block is entered.
        raise RuntimeError("forced transport target construction failure")

    monkeypatch.setattr(MCPSessionActor, "_build_client_target", exploding_build)
    try:
        actor = MCPSessionActor(
            "bad-http",
            {
                "transport": "streamable_http",
                "url": "http://127.0.0.1:1/mcp",
                "headers": {"Authorization": "Bearer token"},
            },
            connect_timeout=2.0,
        )
        with suppress(Exception):
            await actor.start()
        assert actor._http_client is None, "transport HTTP client leaked after failed target build"
    finally:
        monkeypatch.setattr(MCPSessionActor, "_build_client_target", real_build)


@pytest.mark.asyncio
async def test_http_client_closed_after_clean_shutdown() -> None:
    """A served streamable-http session releases its ``httpx2.AsyncClient`` on close."""
    teardown, url = await _start_http_server()
    try:
        actor = MCPSessionActor(
            "httpprobe",
            {
                "transport": "streamable_http",
                "url": url,
                "headers": {"Authorization": "Bearer token"},
            },
            connect_timeout=15.0,
        )
        await actor.start()
        try:
            assert actor.is_healthy() is True
            assert "echo:ok" in str(await actor.call("echo", {"text": "ok"}))
        finally:
            await actor.close()
        assert actor._http_client is None, "transport HTTP client leaked after close"
    finally:
        await teardown()
