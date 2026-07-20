"""Unit tests for AcpRuntime MCP config conversion."""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.acp.runtime.acp_runtime import _mcp_configs_to_acp_stdio
from myrm_agent_harness.toolkits.acp.types import McpServerConfig, RuntimeConfig


def test_mcp_configs_to_acp_stdio_none_or_empty() -> None:
    assert _mcp_configs_to_acp_stdio(None) is None
    assert _mcp_configs_to_acp_stdio([]) is None


def test_mcp_configs_to_acp_stdio_converts_stdio_servers() -> None:
    servers = [
        McpServerConfig(name="fs", command="mcp-fs", args=["--ro"], env={"FOO": "bar"}),
    ]
    converted = _mcp_configs_to_acp_stdio(servers)
    assert converted is not None
    assert len(converted) == 1
    assert converted[0].name == "fs"
    assert converted[0].command == "mcp-fs"
    assert converted[0].args == ["--ro"]
    assert converted[0].env == {"FOO": "bar"}


@pytest.mark.asyncio
async def test_create_session_passes_mcp_servers_when_configured() -> None:
    from unittest.mock import AsyncMock, MagicMock

    from myrm_agent_harness.toolkits.acp.runtime.acp_runtime import AcpRuntime

    config = RuntimeConfig(backend_type="acp", command="claude", cwd="/tmp/ws")
    runtime = AcpRuntime("claude", config)
    runtime._conn = MagicMock()
    runtime._conn.new_session = AsyncMock(return_value=MagicMock(session_id="sess-1"))
    runtime._handler = MagicMock()

    mcp = [McpServerConfig(name="fs", command="mcp-fs", args=[])]
    await runtime._create_session(mcp_servers=mcp)

    runtime._conn.new_session.assert_awaited_once()
    _, kwargs = runtime._conn.new_session.await_args
    assert kwargs["cwd"] == "/tmp/ws"
    assert kwargs["mcp_servers"] is not None
    assert len(kwargs["mcp_servers"]) == 1
    assert runtime._session_id == "sess-1"
