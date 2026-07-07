"""Unit tests: MCP whole-server aggregate demotion."""

from __future__ import annotations

from unittest.mock import MagicMock

from myrm_agent_harness.agent._factory.mcp_routing import (
    AGGREGATE_DIRECT_TOKEN_BUDGET,
    _DirectServerBundle,
    _estimate_schema_tokens,
    _estimate_single_tool_tokens,
    demote_direct_servers_over_budget,
)
from myrm_agent_harness.toolkits.mcp.config import MCPConfig


def _make_mock_tool(name: str, desc_size: int = 50, n_params: int = 2) -> MagicMock:
    tool = MagicMock()
    tool.name = name
    tool.description = f"Tool: {name}" + "x" * desc_size
    props = {f"param_{i}": {"type": "string", "description": "y" * 30} for i in range(n_params)}
    mock_schema = MagicMock()
    mock_schema.schema.return_value = {
        "type": "object",
        "properties": props,
        "required": list(props.keys())[:1],
    }
    tool.get_input_schema = MagicMock(return_value=mock_schema)
    return tool


def _bundle(name: str, tools: list[MagicMock]) -> _DirectServerBundle:
    cfg = MCPConfig(name=name, type="stdio", command="python", args=["-m", name])
    tokens = _estimate_schema_tokens(tools)
    return _DirectServerBundle(config=cfg, tools=tuple(tools), schema_tokens=tokens)


class TestDemoteDirectServersOverBudget:
    def test_under_budget_keeps_all(self) -> None:
        bundles = [_bundle("s1", [_make_mock_tool("t1", 20, 1)])]
        kept, demoted = demote_direct_servers_over_budget(bundles, budget=10000)
        assert len(kept) == 1
        assert demoted == []

    def test_empty_returns_empty(self) -> None:
        kept, demoted = demote_direct_servers_over_budget([])
        assert kept == []
        assert demoted == []

    def test_demotes_largest_server_first(self) -> None:
        small = _bundle("small", [_make_mock_tool("small_t", 30, 1)])
        large = _bundle("large", [_make_mock_tool("large_t", 500, 6)])
        budget = small.schema_tokens + 10
        kept, demoted = demote_direct_servers_over_budget([small, large], budget=budget)
        assert len(kept) == 1
        assert kept[0].config.name == "small"
        assert len(demoted) == 1
        assert demoted[0].name == "large"

    def test_kept_total_within_budget(self) -> None:
        bundles = [
            _bundle(f"s{i}", [_make_mock_tool(f"t_{i}", 300, 4)])
            for i in range(5)
        ]
        kept, _ = demote_direct_servers_over_budget(bundles, budget=1500)
        kept_tokens = sum(b.schema_tokens for b in kept)
        assert kept_tokens <= 1500


class TestEstimateSchemaTokens:
    def test_returns_positive_for_valid_tool(self) -> None:
        tool = _make_mock_tool("test", desc_size=100, n_params=2)
        assert _estimate_single_tool_tokens(tool) > 0

    def test_consistent_with_batch_estimate(self) -> None:
        tool = _make_mock_tool("consistency_check", desc_size=150, n_params=3)
        assert _estimate_single_tool_tokens(tool) == _estimate_schema_tokens([tool])


class TestEstimateSchemaTokens:
    def test_empty_list_returns_zero(self) -> None:
        assert _estimate_schema_tokens([]) == 0

    def test_default_budget_constant(self) -> None:
        assert AGGREGATE_DIRECT_TOKEN_BUDGET == 2700
