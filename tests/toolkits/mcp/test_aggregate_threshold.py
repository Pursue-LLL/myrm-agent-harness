"""Unit tests: MCP aggregate direct-tool token budget guard.

Verifies apply_aggregate_threshold() correctly caps the total schema tokens
of MCP direct tools and overflows the largest tools into deferred.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from myrm_agent_harness.agent._factory.mcp_routing import (
    AGGREGATE_DIRECT_TOKEN_BUDGET,
    FALLBACK_PTC_BRIDGE_TOKENS,
    PTC_OVERHEAD_MULTIPLIER,
    _compute_direct_threshold,
    _estimate_schema_tokens,
    _estimate_single_tool_tokens,
    apply_aggregate_threshold,
)


def _make_mock_tool(name: str, desc_size: int = 50, n_params: int = 2) -> MagicMock:
    """Create a mock BaseTool with controllable schema size."""
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


class TestApplyAggregateThreshold:
    """Tests for apply_aggregate_threshold."""

    def test_under_budget_returns_all(self) -> None:
        """When total tokens <= budget, all tools are kept, none deferred."""
        tools = [_make_mock_tool(f"tool_{i}", desc_size=20, n_params=1) for i in range(3)]
        kept, deferred = apply_aggregate_threshold(tools, budget=10000)
        assert kept == tools
        assert deferred == []

    def test_empty_list_returns_empty(self) -> None:
        """Empty input produces empty output."""
        kept, deferred = apply_aggregate_threshold([])
        assert kept == []
        assert deferred == []

    def test_over_budget_defers_largest_tools(self) -> None:
        """When over budget, largest tools are deferred first."""
        small = _make_mock_tool("small", desc_size=30, n_params=1)
        medium = _make_mock_tool("medium", desc_size=200, n_params=3)
        large = _make_mock_tool("large", desc_size=500, n_params=6)

        small_tokens = _estimate_single_tool_tokens(small)
        medium_tokens = _estimate_single_tool_tokens(medium)
        large_tokens = _estimate_single_tool_tokens(large)

        budget = small_tokens + medium_tokens + 10
        kept, deferred = apply_aggregate_threshold([small, medium, large], budget=budget)

        deferred_names = {t.name for t in deferred}
        kept_names = {t.name for t in kept}

        assert "large" in deferred_names
        assert "small" in kept_names
        assert len(kept) + len(deferred) == 3

    def test_exact_budget_keeps_all(self) -> None:
        """When total tokens == budget exactly, nothing is deferred."""
        tools = [_make_mock_tool(f"tool_{i}", desc_size=100, n_params=2) for i in range(5)]
        exact_budget = _estimate_schema_tokens(tools)
        kept, deferred = apply_aggregate_threshold(tools, budget=exact_budget)
        assert len(deferred) == 0
        assert len(kept) == 5

    def test_all_same_size_defers_overflow(self) -> None:
        """With same-size tools, count-based overflow is deterministic."""
        tools = [_make_mock_tool(f"tool_{i}", desc_size=300, n_params=5) for i in range(20)]
        total = _estimate_schema_tokens(tools)
        assert total > AGGREGATE_DIRECT_TOKEN_BUDGET

        kept, deferred = apply_aggregate_threshold(tools)
        assert len(kept) + len(deferred) == 20
        assert len(deferred) > 0
        kept_total = _estimate_schema_tokens(kept)
        assert kept_total <= AGGREGATE_DIRECT_TOKEN_BUDGET

    def test_single_tool_over_budget(self) -> None:
        """A single tool that exceeds budget is deferred."""
        huge = _make_mock_tool("huge_tool", desc_size=2000, n_params=20)
        huge_tokens = _estimate_single_tool_tokens(huge)

        kept, deferred = apply_aggregate_threshold([huge], budget=huge_tokens - 1)
        assert len(kept) == 0
        assert len(deferred) == 1
        assert deferred[0].name == "huge_tool"

    def test_preserves_tool_identity(self) -> None:
        """Returned tools are the same objects (not copies)."""
        tools = [_make_mock_tool(f"tool_{i}", desc_size=200, n_params=4) for i in range(10)]
        kept, deferred = apply_aggregate_threshold(tools, budget=500)
        all_returned = kept + deferred
        assert set(id(t) for t in all_returned) == set(id(t) for t in tools)

    def test_default_budget_is_constant(self) -> None:
        """Default budget equals the module constant."""
        assert AGGREGATE_DIRECT_TOKEN_BUDGET == 2700

    def test_kept_total_within_budget(self) -> None:
        """Kept tools total tokens must not exceed budget."""
        tools = [_make_mock_tool(f"t_{i}", desc_size=300, n_params=4) for i in range(30)]
        budget = 1500
        kept, deferred = apply_aggregate_threshold(tools, budget=budget)
        kept_tokens = _estimate_schema_tokens(kept)
        assert kept_tokens <= budget

    def test_tool_with_none_description(self) -> None:
        """Tools with None description don't crash the estimator."""
        tool = MagicMock()
        tool.name = "no_desc_tool"
        tool.description = None
        mock_schema = MagicMock()
        mock_schema.schema.return_value = {"type": "object", "properties": {}}
        tool.get_input_schema = MagicMock(return_value=mock_schema)

        kept, deferred = apply_aggregate_threshold([tool], budget=10000)
        assert len(kept) == 1
        assert len(deferred) == 0

    def test_deferred_tools_are_largest(self) -> None:
        """Deferred tools are always larger than or equal to any kept tool."""
        tools = [_make_mock_tool(f"t_{i}", desc_size=50 * (i + 1), n_params=i + 1) for i in range(10)]
        kept, deferred = apply_aggregate_threshold(tools, budget=300)

        if deferred and kept:
            max_kept_size = max(_estimate_single_tool_tokens(t) for t in kept)
            min_deferred_size = min(_estimate_single_tool_tokens(t) for t in deferred)
            assert min_deferred_size >= max_kept_size


class TestEstimateSingleToolTokens:
    """Tests for _estimate_single_tool_tokens helper."""

    def test_returns_positive_for_valid_tool(self) -> None:
        tool = _make_mock_tool("test", desc_size=100, n_params=2)
        tokens = _estimate_single_tool_tokens(tool)
        assert tokens > 0

    def test_consistent_with_batch_estimate(self) -> None:
        """Single-tool estimate matches batch estimate for one tool."""
        tool = _make_mock_tool("consistency_check", desc_size=150, n_params=3)
        single = _estimate_single_tool_tokens(tool)
        batch = _estimate_schema_tokens([tool])
        assert single == batch

    def test_handles_schema_exception(self) -> None:
        """Gracefully handles tools that raise on schema access."""
        tool = MagicMock()
        tool.name = "broken_tool"
        tool.description = "A broken tool"
        tool.get_input_schema.side_effect = RuntimeError("schema error")
        tokens = _estimate_single_tool_tokens(tool)
        assert tokens > 0


class TestEstimateSchemaTokens:
    """Tests for _estimate_schema_tokens batch helper."""

    def test_batch_accumulates_correctly(self) -> None:
        """Batch estimate is approximately sum of individual estimates (rounding tolerance)."""
        tools = [_make_mock_tool(f"tool_{i}", desc_size=80, n_params=2) for i in range(5)]
        batch = _estimate_schema_tokens(tools)
        individual_sum = sum(_estimate_single_tool_tokens(t) for t in tools)
        assert abs(batch - individual_sum) <= len(tools)

    def test_empty_list_returns_zero(self) -> None:
        """Empty tool list produces 0 tokens."""
        assert _estimate_schema_tokens([]) == 0

    def test_exception_in_one_tool_does_not_crash(self) -> None:
        """Batch gracefully handles a tool that raises on schema access."""
        good = _make_mock_tool("good_tool", desc_size=100, n_params=2)
        bad = MagicMock()
        bad.name = "bad_tool"
        bad.description = "A broken tool"
        bad.get_input_schema.side_effect = RuntimeError("schema error")

        tokens = _estimate_schema_tokens([good, bad])
        assert tokens > 0

    def test_tool_without_get_input_schema(self) -> None:
        """Tool lacking get_input_schema attribute uses empty schema."""
        tool = MagicMock(spec=[])
        tool.name = "minimal_tool"
        tool.description = "Minimal"
        tokens = _estimate_schema_tokens([tool])
        assert tokens > 0


class TestComputeDirectThreshold:
    """Tests for _compute_direct_threshold helper."""

    def test_with_no_bridge_tools_uses_fallback(self) -> None:
        """When bridge_tools is None, uses FALLBACK_PTC_BRIDGE_TOKENS."""
        threshold = _compute_direct_threshold(bridge_tools=None)
        assert threshold == FALLBACK_PTC_BRIDGE_TOKENS * PTC_OVERHEAD_MULTIPLIER

    def test_with_empty_bridge_tools_uses_fallback(self) -> None:
        """When bridge_tools is empty sequence, uses fallback."""
        threshold = _compute_direct_threshold(bridge_tools=[])
        assert threshold == FALLBACK_PTC_BRIDGE_TOKENS * PTC_OVERHEAD_MULTIPLIER

    def test_with_bridge_tools_uses_actual_estimate(self) -> None:
        """When bridge_tools provided, threshold is based on their actual schema."""
        bridge = [_make_mock_tool("bridge_tool", desc_size=200, n_params=4)]
        threshold = _compute_direct_threshold(bridge_tools=bridge)
        expected = _estimate_schema_tokens(bridge) * PTC_OVERHEAD_MULTIPLIER
        assert threshold == expected

    def test_returns_positive(self) -> None:
        """Threshold is always a positive integer."""
        assert _compute_direct_threshold() > 0
        tools = [_make_mock_tool("x", desc_size=10, n_params=1)]
        assert _compute_direct_threshold(bridge_tools=tools) > 0


class TestConfigToDict:
    """Tests for _config_to_dict helper."""

    def test_converts_protocol_to_dict(self) -> None:
        """Converts MCPServerConfigProtocol to plain dict."""
        from myrm_agent_harness.agent._factory.mcp_routing import _config_to_dict

        cfg = MagicMock()
        cfg.name = "test_server"
        cfg.type = "stdio"
        cfg.url = None
        cfg.command = "python"
        cfg.args = ["-m", "server"]
        cfg.description = "Test MCP server"
        cfg.extra_params = {"env": {"KEY": "val"}}

        result = _config_to_dict(cfg)
        assert result == {
            "name": "test_server",
            "type": "stdio",
            "url": None,
            "command": "python",
            "args": ["-m", "server"],
            "description": "Test MCP server",
            "extra_params": {"env": {"KEY": "val"}},
        }

    def test_handles_none_values(self) -> None:
        """Works when optional fields are None."""
        from myrm_agent_harness.agent._factory.mcp_routing import _config_to_dict

        cfg = MagicMock()
        cfg.name = "minimal"
        cfg.type = "sse"
        cfg.url = "http://localhost:8080"
        cfg.command = None
        cfg.args = None
        cfg.description = None
        cfg.extra_params = None

        result = _config_to_dict(cfg)
        assert result["name"] == "minimal"
        assert result["command"] is None
        assert result["extra_params"] is None
