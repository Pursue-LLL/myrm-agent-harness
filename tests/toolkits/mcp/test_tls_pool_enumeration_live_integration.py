"""Live TLS / mTLS regression for the two entry points built on top of the session actor.

``test_tls_live_integration`` proves the actor honours TLS settings handed to it directly. Real users reach it through
two other doors that must forward the very same ``MCPConfig`` TLS fields, and a regression in either one silently drops
a custom CA or the client certificate:

- the connection pool (``MCPConnectionManager``) behind every chat turn;
- one-shot tool enumeration (``MCPAgent.get_tools``) behind the "verify server" flow, which captures the server's
  ``initialize`` instructions in the same handshake.

Every negative has a positive control against the same listener, and asserts that the TLS-layer cause is visible in the
surfaced error (a bare ``unhandled errors in a TaskGroup`` would hide it from the user).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest

from myrm_agent_harness.toolkits.mcp.agent import MCPAgent
from myrm_agent_harness.toolkits.mcp.config import MCPConfig
from myrm_agent_harness.toolkits.mcp.connection_manager import MCPConnectionManager
from tests.support.mcp_live_server import serve_probe_mcp
from tests.support.mcp_tls_pki import ABORTED_CONNECTION_MARKERS, VERIFY_FAILURE_MARKERS, TlsPki

_SERVER_NAME = "tls-probe"
_CONNECT_TIMEOUT_SEC = 10.0
_INSTRUCTIONS = "Use echo to repeat text back."
_TRANSPORTS = ("streamable_http", "sse")


def _config(
    transport: str,
    url: str,
    *,
    ssl_verify: bool | str | None = None,
    client_cert: str | None = None,
    client_key: str | None = None,
    client_key_password: str | None = None,
) -> MCPConfig:
    return MCPConfig(
        name=_SERVER_NAME,
        type=transport,
        url=url,
        connect_timeout=_CONNECT_TIMEOUT_SEC,
        ssl_verify=ssl_verify,
        client_cert=client_cert,
        client_key=client_key,
        client_key_password=client_key_password,
    )


def _mtls_config(transport: str, url: str, pki: TlsPki, *, encrypted_key: bool = False) -> MCPConfig:
    return _config(
        transport,
        url,
        ssl_verify=str(pki.ca_cert),
        client_cert=str(pki.client_cert),
        client_key=str(pki.client_key_encrypted if encrypted_key else pki.client_key),
        client_key_password=pki.client_key_passphrase if encrypted_key else None,
    )


@asynccontextmanager
async def _pool() -> AsyncIterator[MCPConnectionManager]:
    """A private pool (not the process singleton) that always releases its warm sessions."""
    manager = MCPConnectionManager()
    try:
        yield manager
    finally:
        await manager.close_all()


def _failure_text(exc: BaseException) -> str:
    return str(exc).lower()


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", _TRANSPORTS)
async def test_pool_forwards_the_custom_ca(pki: TlsPki, transport: str) -> None:
    async with serve_probe_mcp(transport, tls=pki) as url, _pool() as pool:
        conn = await pool.get_connection([_config(transport, url, ssl_verify=str(pki.ca_cert))])
        assert "echo:ping" in str(await conn.call(_SERVER_NAME, "echo", {"text": "ping"}))


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", _TRANSPORTS)
@pytest.mark.parametrize("encrypted_key", [False, True], ids=["plain-key", "passphrase-key"])
async def test_pool_forwards_the_mtls_client_material(pki: TlsPki, transport: str, encrypted_key: bool) -> None:
    async with serve_probe_mcp(transport, tls=pki, require_client_cert=True) as url, _pool() as pool:
        conn = await pool.get_connection([_mtls_config(transport, url, pki, encrypted_key=encrypted_key)])
        assert "echo:mtls" in str(await conn.call(_SERVER_NAME, "echo", {"text": "mtls"}))


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", _TRANSPORTS)
async def test_pool_surfaces_the_tls_cause_then_backs_off_until_auth_is_refreshed(pki: TlsPki, transport: str) -> None:
    async with serve_probe_mcp(transport, tls=pki) as url, _pool() as pool:
        untrusted = [_config(transport, url)]

        with pytest.raises(RuntimeError, match="All MCP servers failed to start") as first:
            await pool.get_connection(untrusted)
        assert any(marker in _failure_text(first.value) for marker in VERIFY_FAILURE_MARKERS), first.value

        # The circuit breaker refuses the immediate retry instead of hammering a dead server.
        with pytest.raises(RuntimeError, match="startup backoff cooldown"):
            await pool.get_connection(untrusted)

        # Re-authorising the server resets the breaker, so the next attempt really connects (and fails on TLS again).
        pool.refresh_server_auth(_SERVER_NAME, {})
        with pytest.raises(RuntimeError, match="All MCP servers failed to start") as retried:
            await pool.get_connection(untrusted)
        assert "cooldown" not in _failure_text(retried.value)
        assert any(marker in _failure_text(retried.value) for marker in VERIFY_FAILURE_MARKERS), retried.value

        # Positive control: the same listener serves a client that trusts its CA.
        conn = await pool.get_connection([_config(transport, url, ssl_verify=str(pki.ca_cert))])
        assert "echo:ok" in str(await conn.call(_SERVER_NAME, "echo", {"text": "ok"}))


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", _TRANSPORTS)
async def test_enumeration_over_tls_lists_tools_and_captures_instructions(pki: TlsPki, transport: str) -> None:
    async with serve_probe_mcp(transport, tls=pki, instructions=_INSTRUCTIONS) as url:
        agent = MCPAgent()
        tools = await agent.get_tools([_config(transport, url, ssl_verify=str(pki.ca_cert))])

        assert sorted(tool.name.rsplit("__", 1)[-1] for tool in tools) == ["add", "echo"]
        # The same handshake yields the server instructions, so verification never needs a second connection.
        assert agent.get_server_instructions(_SERVER_NAME) == _INSTRUCTIONS
        assert agent.get_server_instructions("never-enumerated") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", _TRANSPORTS)
async def test_enumeration_surfaces_the_tls_cause_for_an_untrusted_server(pki: TlsPki, transport: str) -> None:
    async with serve_probe_mcp(transport, tls=pki) as url:
        agent = MCPAgent()
        with pytest.raises(RuntimeError, match=f"Failed to get tools from {_SERVER_NAME}") as excinfo:
            await agent.get_tools([_config(transport, url)])
        assert any(marker in _failure_text(excinfo.value) for marker in VERIFY_FAILURE_MARKERS), excinfo.value

        # Positive control: the same listener enumerates once its CA is trusted.
        assert await agent.get_tools([_config(transport, url, ssl_verify=str(pki.ca_cert))])


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", _TRANSPORTS)
@pytest.mark.parametrize("encrypted_key", [False, True], ids=["plain-key", "passphrase-key"])
async def test_enumeration_over_mtls_needs_the_client_certificate(
    pki: TlsPki, transport: str, encrypted_key: bool
) -> None:
    async with serve_probe_mcp(transport, tls=pki, require_client_cert=True) as url:
        agent = MCPAgent()
        no_client_cert = _config(transport, url, ssl_verify=str(pki.ca_cert))
        with pytest.raises(RuntimeError, match="Failed to get tools") as excinfo:
            await agent.get_tools([no_client_cert])
        assert any(marker in _failure_text(excinfo.value) for marker in ABORTED_CONNECTION_MARKERS), excinfo.value

        tools = await agent.get_tools([_mtls_config(transport, url, pki, encrypted_key=encrypted_key)])
        assert sorted(tool.name.rsplit("__", 1)[-1] for tool in tools) == ["add", "echo"]
