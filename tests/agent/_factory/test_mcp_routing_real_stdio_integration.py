"""Integration proof: real stdio MCP with 50+ tools routes to PTC/Skill path."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from myrm_agent_harness.agent._factory.mcp_routing import (
    compute_direct_threshold,
    route_mcp_servers,
)
from myrm_agent_harness.agent.skills.runtime.registry import skill_registry
from myrm_agent_harness.toolkits.mcp.config import MCPConfig
from myrm_agent_harness.toolkits.mcp.connection_manager import MCPConnectionManager

_MEGA_TOOL_COUNT = 55


def _write_mega_mcp_server(
    script_path: Path, tool_count: int = _MEGA_TOOL_COUNT
) -> None:
    lines = [
        "from mcp.server.fastmcp import FastMCP",
        "",
        'server = FastMCP("mega-routing-probe")',
        "",
    ]
    for i in range(tool_count):
        lines.extend(
            [
                "@server.tool()",
                f"def mega_tool_{i}(",
                "    query: str,",
                "    limit: int = 10,",
                '    filter_mode: str = "all",',
                ") -> str:",
                f'    """Mega routing probe tool {i} with extended semantics for schema token budget."""',
                '    return f"{query}:{limit}:{filter_mode}"',
                "",
            ]
        )
    lines.extend(
        [
            'if __name__ == "__main__":',
            '    server.run(transport="stdio")',
        ]
    )
    script_path.write_text("\n".join(lines), encoding="utf-8")


@pytest.fixture
def _reset_manager() -> object:
    MCPConnectionManager._instance = None
    skill_registry.clear()
    yield
    MCPConnectionManager._instance = None
    skill_registry.clear()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_route_mcp_servers_real_stdio_mega_server_ptc_path(
    tmp_path: Path,
    _reset_manager: object,
) -> None:
    """Real FastMCP stdio server with 55 tools must demote to PTC/Skill (no mocks)."""
    script = tmp_path / "mega_routing_probe.py"
    _write_mega_mcp_server(script)

    cfg = MCPConfig(
        name="mega-routing-probe",
        type="stdio",
        command=sys.executable,
        args=[str(script)],
        description="Real mega MCP routing integration probe",
        connect_timeout=45.0,
    )

    threshold = compute_direct_threshold()
    manager = await MCPConnectionManager.get_instance()
    try:
        conn = await manager.get_connection([cfg])
        server_tools = conn.tools_by_server.get(cfg.name) or []
        assert len(server_tools) >= 50, f"expected >=50 tools, got {len(server_tools)}"

        result = await route_mcp_servers([cfg])

        assert (
            result.direct_tools == []
        ), f"expected PTC path (0 direct tools), got {len(result.direct_tools)}; threshold={threshold}"
        assert (
            len(result.skills) == 1
        ), f"expected 1 PTC skill, got {len(result.skills)}"

        skill = result.skills[0]
        assert skill.mcp is not None
        assert skill.mcp.server == "mega-routing-probe"
        assert len(skill.mcp.tools) >= 50
    finally:
        await manager.stop()
