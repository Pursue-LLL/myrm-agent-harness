"""Real-path coverage for ``MCPSessionActor`` scenarios the unit suite skips.

Real-wire integration (no mocks on the transport):
- resource reads against a real stdio MCP server (text content + missing-URI
  error without triggering a reconnect);
- ``start()`` failing against an unreachable endpoint.

Logic paths that do not cross the wire (the wire itself is covered by
``test_session_transports_integration.py``):
- ``update_auth_headers`` merge semantics;
- ``_refresh_auth_headers`` provider refresh / stdio skip / provider failure;
- ``_build_client_target`` HTTP-without-URL error and the SSE branch;
- dynamic tool refresh blocked by runtime posture keeps the previous map.
"""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mcp.shared.exceptions import MCPError

from myrm_agent_harness.toolkits.mcp.config import MCPConfig
from myrm_agent_harness.toolkits.mcp.connection_manager import MCPConnectionManager
from myrm_agent_harness.toolkits.mcp.session_actor import MCPSessionActor

# A real stdio MCP server exposing one tool plus a template resource.
_RESOURCE_SERVER_SRC = """
import sys

from mcp.server.mcpserver import MCPServer

server = MCPServer("res-probe")


@server.tool()
def echo(text: str) -> str:
    return f"echo:{text}"


@server.resource("greeting://{name}")
def greeting(name: str) -> str:
    return f"Hello, {name}!"


if __name__ == "__main__":
    server.run(transport="stdio")
"""


@pytest.fixture
def _reset_manager() -> object:
    MCPConnectionManager._instance = None
    yield
    MCPConnectionManager._instance = None


# ---------------------------------------------------------------------------
# Real-wire: resource reads via the production pool over a stdio subprocess.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_resource_real_stdio_server(tmp_path, _reset_manager: object) -> None:
    """A template resource is fetched through the pool over a real subprocess."""
    script = tmp_path / "res_server.py"
    script.write_text(_RESOURCE_SERVER_SRC, encoding="utf-8")

    cfg = MCPConfig(
        name="resprobe",
        type="stdio",
        command=sys.executable,
        args=[str(script)],
        description="resource probe",
        connect_timeout=30.0,
    )
    manager = await MCPConnectionManager.get_instance()
    try:
        conn = await manager.get_connection([cfg])
        data = await conn.read_resource("resprobe", "greeting://world")
        assert data == b"Hello, world!"
        # Session stays healthy and still serves tool calls after the read.
        assert "echo:hi" in str(await conn.call("resprobe", "echo", {"text": "hi"}))
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_read_resource_missing_uri_does_not_reconnect(tmp_path, _reset_manager: object) -> None:
    """A bad resource URI fails the read but never triggers a reconnect."""
    script = tmp_path / "res_server.py"
    script.write_text(_RESOURCE_SERVER_SRC, encoding="utf-8")

    cfg = MCPConfig(
        name="resprobe",
        type="stdio",
        command=sys.executable,
        args=[str(script)],
        description="resource probe",
        connect_timeout=30.0,
    )
    manager = await MCPConnectionManager.get_instance()
    try:
        conn = await manager.get_connection([cfg])
        actor = conn._resolve_actor("resprobe")
        assert actor is not None
        healthy_before = actor.is_healthy()
        with pytest.raises(MCPError):
            await conn.read_resource("resprobe", "nope://not-a-resource")
        # Non-transport failure: the session must still be healthy and serving.
        assert actor.is_healthy() is healthy_before
        assert "echo:ok" in str(await conn.call("resprobe", "echo", {"text": "ok"}))
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_start_fails_when_server_unreachable() -> None:
    """A server that cannot be reached fails loudly instead of hanging."""
    actor = MCPSessionActor(
        "unreachable",
        {"transport": "streamable_http", "url": "http://127.0.0.1:1/mcp"},
        connect_timeout=1.0,
    )
    with pytest.raises(RuntimeError, match="failed to start"):
        await actor.start()
    assert actor.is_healthy() is False


# ---------------------------------------------------------------------------
# Auth: header merge + provider-driven refresh on reconnect.
# ---------------------------------------------------------------------------


def test_update_auth_headers_merges_with_existing() -> None:
    actor = MCPSessionActor(
        "srv",
        {
            "transport": "streamable_http",
            "url": "http://x/mcp",
            "headers": {"Authorization": "Bearer old", "X-Id": "keep"},
        },
    )
    actor.update_auth_headers({"Authorization": "Bearer new", "X-New": "v"})

    headers = actor._connection["headers"]
    assert headers["Authorization"] == "Bearer new"
    assert headers["X-Id"] == "keep"
    assert headers["X-New"] == "v"


@pytest.mark.asyncio
async def test_refresh_auth_headers_uses_provider() -> None:
    provider = MagicMock()
    provider.get_auth_headers = AsyncMock(return_value={"Authorization": "Bearer fresh"})
    conn = {
        "transport": "streamable_http",
        "url": "http://x/mcp",
        "headers": {"Authorization": "Bearer old"},
    }
    actor = MCPSessionActor("srv", conn, auth_provider=provider)

    await actor._refresh_auth_headers(conn)

    assert conn["headers"]["Authorization"] == "Bearer fresh"
    assert actor._connection["headers"]["Authorization"] == "Bearer fresh"
    provider.get_auth_headers.assert_awaited_once_with("srv", "http://x/mcp")


@pytest.mark.asyncio
async def test_refresh_auth_headers_skipped_for_stdio() -> None:
    provider = MagicMock()
    provider.get_auth_headers = AsyncMock()
    actor = MCPSessionActor("srv", {"transport": "stdio"}, auth_provider=provider)

    await actor._refresh_auth_headers({"transport": "stdio"})

    provider.get_auth_headers.assert_not_awaited()


@pytest.mark.asyncio
async def test_refresh_auth_headers_provider_error_is_silent() -> None:
    provider = MagicMock()
    provider.get_auth_headers = AsyncMock(side_effect=RuntimeError("provider down"))
    conn = {"transport": "streamable_http", "url": "http://x/mcp"}
    actor = MCPSessionActor("srv", conn, auth_provider=provider)

    await actor._refresh_auth_headers(conn)  # must not raise

    assert conn.get("headers") in (None, {}) or "Authorization" not in conn["headers"]


# ---------------------------------------------------------------------------
# _build_client_target branches.
# ---------------------------------------------------------------------------


def test_build_client_target_http_missing_url_raises() -> None:
    actor = MCPSessionActor("srv", {"transport": "streamable_http"})
    with pytest.raises(ValueError, match="requires 'url'"):
        actor._build_client_target({"transport": "streamable_http"})


def test_build_client_target_sse_branch() -> None:
    actor = MCPSessionActor("srv", {"transport": "sse"})
    headers = {"Authorization": "Bearer x"}
    with patch("mcp.client.sse.sse_client", return_value="sse-target") as mock_sse:
        target = actor._build_client_target({"transport": "sse", "url": "https://example.com/sse", "headers": headers})
    assert target == "sse-target"
    mock_sse.assert_called_once_with("https://example.com/sse", headers=headers)


# ---------------------------------------------------------------------------
# Dynamic refresh gated by runtime posture keeps the previous tool map.
# ---------------------------------------------------------------------------


class _StubTool:
    def __init__(self, name: str, description: str = "Safe operation.") -> None:
        self.name = name
        self.description = description


@pytest.mark.asyncio
async def test_refresh_tools_dynamic_posture_block_keeps_old() -> None:
    """A high-risk tool surfaced by a dynamic refresh is rejected, old map kept."""
    actor = MCPSessionActor("srv", {"transport": "stdio"})
    old_tool = _StubTool("mcp__srv__keep")
    actor._tools = {"mcp__srv__keep": old_tool}

    risky_tool = _StubTool("mcp__srv__evil_ignore_prior_instructions")
    session = MagicMock()
    session.list_tools = AsyncMock(return_value=MagicMock())
    session.call_tool = AsyncMock()

    with (
        patch(
            "myrm_agent_harness.toolkits.mcp.tool_converter.convert_mcp_tools",
            return_value=[risky_tool],
        ),
        patch(
            "myrm_agent_harness.toolkits.mcp.agent.MCPAgent.process_session_tools",
            return_value=[risky_tool],
        ),
    ):
        await actor._refresh_tools(session)

    assert "mcp__srv__keep" in actor._tools
    assert "mcp__srv__evil_ignore_prior_instructions" not in actor._tools
