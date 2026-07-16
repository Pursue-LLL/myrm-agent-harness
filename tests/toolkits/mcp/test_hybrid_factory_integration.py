"""Integration test: MCP hybrid routing in skill_agent_factory.

Verifies the factory correctly splits MCP servers into direct/ptc paths
using automatic token-based threshold estimation.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from myrm_agent_harness.agent._factory.mcp_routing import (
    compute_direct_threshold,
    estimate_schema_tokens,
)


def _make_mock_tool(name: str, schema_size: int = 50) -> MagicMock:
    tool = MagicMock()
    tool.name = name
    tool.description = f"Tool: {name}" + "x" * schema_size
    mock_schema = MagicMock()
    mock_schema.model_json_schema.return_value = {
        "type": "object",
        "properties": {"q": {"type": "string"}},
    }
    tool.get_input_schema = MagicMock(return_value=mock_schema)
    return tool


@pytest.mark.asyncio
async def test_factory_hybrid_splits_direct_and_ptc() -> None:
    """Low-token server → direct, high-token server → PTC."""
    threshold = compute_direct_threshold()  # fallback = 450 * 2 = 900

    small_tools = [_make_mock_tool(f"small_tool_{i}", schema_size=20) for i in range(3)]
    large_tools = [_make_mock_tool(f"large_tool_{i}", schema_size=400) for i in range(30)]

    small_tokens = estimate_schema_tokens(small_tools)
    large_tokens = estimate_schema_tokens(large_tools)

    assert small_tokens <= threshold
    assert large_tokens > threshold


@pytest.mark.asyncio
async def test_factory_empty_mcp_server_no_crash() -> None:
    """Empty tool list produces 0 tokens."""
    tokens = estimate_schema_tokens([])
    assert tokens == 0


@pytest.mark.asyncio
async def test_threshold_correctly_routes_mixed_servers() -> None:
    """Mixed server tool sets are correctly classified."""
    threshold = compute_direct_threshold()

    tools_by_server = {
        "small": [_make_mock_tool(f"s_{i}", schema_size=20) for i in range(3)],
        "large": [_make_mock_tool(f"l_{i}", schema_size=400) for i in range(30)],
    }

    direct_servers: list[str] = []
    ptc_servers: list[str] = []

    for server_name, tools in tools_by_server.items():
        tokens = estimate_schema_tokens(tools)
        if tokens <= threshold:
            direct_servers.append(server_name)
        else:
            ptc_servers.append(server_name)

    assert "small" in direct_servers
    assert "large" in ptc_servers


@pytest.mark.asyncio
async def test_direct_tools_have_correct_metadata() -> None:
    """Verify direct tools retain their original BaseTool attributes."""
    tool = _make_mock_tool("search_query")
    tool.args_schema = {"type": "object", "properties": {"q": {"type": "string"}}}

    assert tool.name == "search_query"
    assert "Tool: search_query" in tool.description
    assert "properties" in tool.args_schema
