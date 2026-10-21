"""Launch gates on the one-shot enumeration path (the "verify server" flow).

Enumeration spawns a stdio server exactly like a warm session does, so it must refuse the same launches: an untrusted
workspace or an OSV malware advisory ends enumeration before anything is spawned, and the reason reaches the caller.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.toolkits.mcp import agent as agent_module
from myrm_agent_harness.toolkits.mcp.agent import MCPAgent
from myrm_agent_harness.toolkits.mcp.config import MCPConfig
from tests.support.mcp_launch_gates import PATCH_OSV_CHECK, PATCH_TRUST_GATE, RecordingTrustGate


@pytest.mark.asyncio
async def test_enumeration_refuses_a_server_flagged_as_malware() -> None:
    cfg = MCPConfig(name="evil", type="stdio", command="npx", args=["-y", "flatmap-stream"])
    osv = AsyncMock(return_value="MAL-2025-0001")

    with (
        patch(PATCH_OSV_CHECK, osv),
        patch(PATCH_TRUST_GATE, return_value=None),
        patch.object(MCPAgent, "_build_enumeration_target") as build_target,
    ):
        name, tools, error = await MCPAgent()._enumerate_server_tools(cfg)

    assert (name, tools) == ("evil", [])
    assert error == "MCP security check failed for 'evil': Malware advisory detected: MAL-2025-0001"
    osv.assert_awaited_once_with("npx", ["-y", "flatmap-stream"], use_cache=True)
    build_target.assert_not_called()  # nothing was spawned


@pytest.mark.asyncio
async def test_enumeration_refuses_a_launch_the_workspace_trust_gate_denies() -> None:
    cfg = MCPConfig(
        name="plugin",
        type="stdio",
        command="./bin/srv",
        extra_params={"cwd": "/work/plugin", "plugin_root": "/work/plugin"},
    )
    gate = RecordingTrustGate(deny=True)
    osv = AsyncMock(return_value=None)

    with (
        patch(PATCH_OSV_CHECK, osv),
        patch(PATCH_TRUST_GATE, return_value=gate),
        patch.object(MCPAgent, "_build_enumeration_target") as build_target,
    ):
        name, tools, error = await MCPAgent()._enumerate_server_tools(cfg)

    assert (name, tools, error) == ("plugin", [], "workspace is not trusted")
    assert gate.requests == [
        {"workspace_root": None, "cwd": "/work/plugin", "plugin_root": "/work/plugin", "trust_level": "untrusted"}
    ]
    osv.assert_not_awaited()
    build_target.assert_not_called()


@pytest.mark.asyncio
async def test_enumeration_ignores_blank_launch_hints_and_proceeds_when_the_gates_allow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(agent_module, "_TOOL_FETCH_RETRY_BACKOFF", 0.0)
    cfg = MCPConfig(name="fine", type="stdio", command="npx", args=["-y", "left-pad"], extra_params={"cwd": ""})
    gate = RecordingTrustGate(deny=False, trust_level="trusted")
    allowed = AsyncMock(return_value=None)

    with (
        patch(PATCH_OSV_CHECK, allowed),
        patch(PATCH_TRUST_GATE, return_value=gate),
        patch.object(MCPAgent, "_build_enumeration_target", side_effect=RuntimeError("reached transport")) as build,
    ):
        _, tools, error = await MCPAgent()._enumerate_server_tools(cfg)

    assert tools == []
    assert error is not None
    assert "reached transport" in error  # the gates let it through; only the transport stub stopped it
    assert build.call_count == agent_module._TOOL_FETCH_MAX_ATTEMPTS
    allowed.assert_awaited_once_with("npx", ["-y", "left-pad"], use_cache=True)
    # A blank cwd hint is treated as absent, not forwarded as an empty path.
    assert gate.requests == [{"workspace_root": None, "cwd": None, "plugin_root": None, "trust_level": "trusted"}]
