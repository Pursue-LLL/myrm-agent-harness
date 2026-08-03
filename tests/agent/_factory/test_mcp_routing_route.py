"""Unit tests for route_mcp_servers and PTC skill generation wiring."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent._factory.mcp_routing import (
    MCPRoutingResult,
    _compress_direct_tools,
    demote_direct_servers_over_budget,
    estimate_single_tool_tokens,
    route_mcp_servers,
)
from myrm_agent_harness.agent._factory.mcp_surface import MCPSurfaceMode
from myrm_agent_harness.backends.skills.types import MCPSkillData, SkillMetadata
from myrm_agent_harness.toolkits.mcp.config import MCPConfig


def _make_mock_tool(
    name: str, schema_size: int = 50, *, param_props: int = 1
) -> MagicMock:
    tool = MagicMock()
    tool.name = name
    tool.description = f"Tool {name}"
    properties = {
        f"field_{i}": {"type": "string", "description": "x" * schema_size}
        for i in range(param_props)
    }
    mock_schema = MagicMock()
    mock_schema.model_json_schema.return_value = {
        "type": "object",
        "properties": properties,
    }
    tool.get_input_schema = MagicMock(return_value=mock_schema)
    return tool


def _mock_connection(tools_by_server: dict[str, list[MagicMock]]) -> MagicMock:
    conn = MagicMock()
    conn.tools_by_server = tools_by_server
    return conn


@pytest.mark.asyncio
async def test_route_mcp_servers_direct_path() -> None:
    cfg = MCPConfig(name="small", type="stdio", command="echo")
    tools = [_make_mock_tool(f"tool_{i}", schema_size=20) for i in range(2)]
    manager = MagicMock()
    manager.get_connection = AsyncMock(return_value=_mock_connection({"small": tools}))

    with patch(
        "myrm_agent_harness.toolkits.mcp.connection_manager.get_mcp_connection_manager",
        AsyncMock(return_value=manager),
    ):
        result = await route_mcp_servers([cfg])

    assert isinstance(result, MCPRoutingResult)
    assert len(result.direct_tools) == 2
    assert result.skills == []


@pytest.mark.asyncio
async def test_route_mcp_servers_ptc_path() -> None:
    cfg = MCPConfig(name="large", type="stdio", command="echo")
    tools = [_make_mock_tool(f"tool_{i}", schema_size=500) for i in range(30)]
    manager = MagicMock()
    manager.get_connection = AsyncMock(return_value=_mock_connection({"large": tools}))

    skill_meta = SkillMetadata(
        name="mcp_large_skill",
        description="Large MCP",
        mcp=MCPSkillData(
            server="large",
            tools=["tool_0"],
            config=[{"name": "large", "type": "stdio", "command": "echo"}],
        ),
    )

    with (
        patch(
            "myrm_agent_harness.toolkits.mcp.connection_manager.get_mcp_connection_manager",
            AsyncMock(return_value=manager),
        ),
        patch(
            "myrm_agent_harness.agent.skills.mcp.core_generator.mcp_skill_generator.generate_metadata_only",
            AsyncMock(return_value=[skill_meta]),
        ),
        patch(
            "myrm_agent_harness.agent.skills.runtime.registry.skill_registry.register"
        ) as register_mock,
    ):
        result = await route_mcp_servers([cfg])

    assert result.direct_tools == []
    assert len(result.skills) == 1
    register_mock.assert_called_once_with(skill_meta)


@pytest.mark.asyncio
async def test_route_mcp_servers_clears_mcp_registry_before_routing() -> None:
    with patch(
        "myrm_agent_harness.agent.skills.runtime.registry.skill_registry.clear_mcp_skills"
    ) as clear_mock:
        manager = MagicMock()
        manager.get_connection = AsyncMock(
            return_value=_mock_connection({}),
        )
        with patch(
            "myrm_agent_harness.toolkits.mcp.connection_manager.get_mcp_connection_manager",
            AsyncMock(return_value=manager),
        ):
            await route_mcp_servers([])

    clear_mock.assert_called_once()


@pytest.mark.asyncio
async def test_route_mcp_servers_skips_failed_connection() -> None:
    cfg = MCPConfig(name="broken", type="stdio", command="echo")
    manager = MagicMock()
    manager.get_connection = AsyncMock(side_effect=RuntimeError("connection refused"))

    with patch(
        "myrm_agent_harness.toolkits.mcp.connection_manager.get_mcp_connection_manager",
        AsyncMock(return_value=manager),
    ):
        result = await route_mcp_servers([cfg])

    assert result.direct_tools == []
    assert result.skills == []


@pytest.mark.asyncio
async def test_route_mcp_servers_skips_empty_tools() -> None:
    cfg = MCPConfig(name="empty", type="stdio", command="echo")
    manager = MagicMock()
    manager.get_connection = AsyncMock(return_value=_mock_connection({"empty": []}))

    with patch(
        "myrm_agent_harness.toolkits.mcp.connection_manager.get_mcp_connection_manager",
        AsyncMock(return_value=manager),
    ):
        result = await route_mcp_servers([cfg])

    assert result.direct_tools == []
    assert result.skills == []


@pytest.mark.asyncio
async def test_route_mcp_servers_aggregate_demotion() -> None:
    """Multiple small servers can demote largest when aggregate budget exceeded."""
    cfg_a = MCPConfig(name="server_a", type="stdio", command="echo")
    cfg_b = MCPConfig(name="server_b", type="stdio", command="echo")
    tools_a = [
        _make_mock_tool(f"a_{i}", schema_size=400, param_props=4) for i in range(3)
    ]
    tools_b = [
        _make_mock_tool(f"b_{i}", schema_size=400, param_props=4) for i in range(3)
    ]

    async def get_connection(_configs: list[MCPConfig]) -> MagicMock:
        name = _configs[0].name
        if name == "server_a":
            return _mock_connection({"server_a": tools_a})
        return _mock_connection({"server_b": tools_b})

    manager = MagicMock()
    manager.get_connection = get_connection

    skill_meta = SkillMetadata(
        name="mcp_demoted_skill",
        description="Demoted",
        mcp=MCPSkillData(
            server="server_a",
            tools=["a_0"],
            config=[{"name": "server_a", "type": "stdio", "command": "echo"}],
        ),
    )

    with (
        patch(
            "myrm_agent_harness.agent._factory.mcp_routing.compute_direct_threshold",
            return_value=10000,
        ),
        patch(
            "myrm_agent_harness.agent._factory.mcp_routing.demote_direct_servers_over_budget",
            lambda bundles: demote_direct_servers_over_budget(bundles, budget=1500),
        ),
        patch(
            "myrm_agent_harness.toolkits.mcp.connection_manager.get_mcp_connection_manager",
            AsyncMock(return_value=manager),
        ),
        patch(
            "myrm_agent_harness.agent.skills.mcp.core_generator.mcp_skill_generator.generate_metadata_only",
            AsyncMock(return_value=[skill_meta]),
        ),
        patch(
            "myrm_agent_harness.agent.skills.runtime.registry.skill_registry.register"
        ),
    ):
        result = await route_mcp_servers(
            [cfg_a, cfg_b],
            surface_mode=MCPSurfaceMode.AUTO,
        )

    assert len(result.direct_tools) > 0
    assert len(result.skills) == 1


@pytest.mark.asyncio
async def test_route_mcp_servers_aggregate_over_budget_demotes_to_ptc() -> None:
    """Aggregate direct schema over budget demotes to MCP→Skill (no catalog_invoke)."""
    cfg = MCPConfig(name="medium", type="stdio", command="echo")
    tools = [_make_mock_tool(f"tool_{i}", schema_size=200, param_props=3) for i in range(8)]
    manager = MagicMock()
    manager.get_connection = AsyncMock(return_value=_mock_connection({"medium": tools}))

    skill_meta = SkillMetadata(
        name="mcp_medium_skill",
        description="Medium MCP",
        mcp=MCPSkillData(
            server="medium",
            tools=["tool_0"],
            config=[{"name": "medium", "type": "stdio", "command": "echo"}],
        ),
    )

    with (
        patch(
            "myrm_agent_harness.agent._factory.mcp_routing.compute_direct_threshold",
            return_value=10000,
        ),
        patch(
            "myrm_agent_harness.toolkits.mcp.connection_manager.get_mcp_connection_manager",
            AsyncMock(return_value=manager),
        ),
        patch(
            "myrm_agent_harness.agent.skills.mcp.core_generator.mcp_skill_generator.generate_metadata_only",
            AsyncMock(return_value=[skill_meta]),
        ),
        patch(
            "myrm_agent_harness.agent.skills.runtime.registry.skill_registry.register"
        ),
    ):
        result = await route_mcp_servers([cfg], surface_mode=MCPSurfaceMode.AUTO)

    assert result.direct_tools == []
    assert len(result.skills) == 1


class TestCompressDirectToolsEdgeCases:
    def test_model_copy_name_mismatch_falls_back(self) -> None:
        tool = _make_mock_tool("verbose")
        tool.description = "Tool verbose" + "x" * 2000

        def bad_copy(*, update: dict[str, str]) -> MagicMock:
            cloned = _make_mock_tool("wrong_name", schema_size=10)
            cloned.description = update["description"]
            return cloned

        tool.model_copy = bad_copy
        compressed = _compress_direct_tools([tool])[0]
        assert compressed.description != tool.description
        assert len(compressed.description) < len(tool.description)

    def test_model_copy_exception_falls_back_to_copy(self) -> None:
        tool = _make_mock_tool("verbose")
        tool.description = "Tool verbose" + "x" * 2000

        def raise_copy(*, update: dict[str, str]) -> MagicMock:
            raise TypeError("model_copy failed")

        tool.model_copy = raise_copy
        compressed = _compress_direct_tools([tool])[0]
        assert len(compressed.description) < len(tool.description)

    def test_copy_failure_keeps_original(self) -> None:
        tool = _make_mock_tool("verbose")
        tool.description = "Tool verbose" + "x" * 2000
        tool.model_copy = None

        class ImmutableDesc:
            @property
            def description(self) -> str:
                return tool.description

            @description.setter
            def description(self, _value: str) -> None:
                raise AttributeError("read-only")

        fallback = ImmutableDesc()
        fallback.name = tool.name  # type: ignore[attr-defined]
        fallback.get_input_schema = tool.get_input_schema  # type: ignore[attr-defined]

        with patch(
            "myrm_agent_harness.agent._factory.mcp_routing.copy.copy",
            return_value=fallback,
        ):
            compressed = _compress_direct_tools([tool])[0]
        assert compressed is tool


class TestEstimateSingleToolTokens:
    def test_returns_positive_for_valid_tool(self) -> None:
        tool = _make_mock_tool("single")
        assert estimate_single_tool_tokens(tool) > 0
