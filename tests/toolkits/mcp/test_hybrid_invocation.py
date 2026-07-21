"""Tests for MCP Hybrid Invocation routing.

Verifies:
- estimate_schema_tokens correctly estimates token count from tool schemas
- Auto routing decision: ≤threshold → direct, >threshold → PTC
- MCPAgent._normalize_mcp_result handles all langchain_mcp_adapters formats
"""

from __future__ import annotations

from unittest.mock import MagicMock

from myrm_agent_harness.agent._factory.mcp_routing import (
    FALLBACK_PTC_BRIDGE_TOKENS,
    PTC_OVERHEAD_MULTIPLIER,
    _config_to_dict,
    compute_direct_threshold,
    estimate_schema_tokens,
)
from myrm_agent_harness.toolkits.mcp.config import MCPConfig


def _make_mock_tool(name: str, schema_size: int = 50) -> MagicMock:
    tool = MagicMock()
    tool.name = name
    tool.description = f"Mock tool {name}" + "x" * schema_size
    mock_schema = MagicMock()
    mock_schema.model_json_schema.return_value = {
        "type": "object",
        "properties": {"q": {"type": "string"}},
    }
    tool.get_input_schema = MagicMock(return_value=mock_schema)
    return tool


class TestEstimateSchemaTokens:
    """Test estimate_schema_tokens utility."""

    def test_returns_positive_integer(self) -> None:
        tools = [_make_mock_tool(f"t{i}") for i in range(3)]
        tokens = estimate_schema_tokens(tools)
        assert tokens > 0
        assert isinstance(tokens, int)

    def test_scales_with_tool_count(self) -> None:
        tools_3 = [_make_mock_tool(f"t{i}") for i in range(3)]
        tools_10 = [_make_mock_tool(f"t{i}") for i in range(10)]
        assert estimate_schema_tokens(tools_10) > estimate_schema_tokens(tools_3)

    def test_scales_with_schema_size(self) -> None:
        small = [_make_mock_tool("s", schema_size=10)]
        large = [_make_mock_tool("l", schema_size=500)]
        assert estimate_schema_tokens(large) > estimate_schema_tokens(small)

    def test_empty_tools_returns_zero(self) -> None:
        assert estimate_schema_tokens([]) == 0

    def test_handles_tool_without_get_input_schema(self) -> None:
        tool = MagicMock()
        tool.name = "broken"
        tool.description = "no schema"
        del tool.get_input_schema
        tokens = estimate_schema_tokens([tool])
        assert tokens > 0


class TestDynamicThreshold:
    """Test compute_direct_threshold based on PTC bridge overhead."""

    def test_fallback_without_bridge_tools(self) -> None:
        threshold = compute_direct_threshold()
        assert threshold == FALLBACK_PTC_BRIDGE_TOKENS * PTC_OVERHEAD_MULTIPLIER

    def test_with_actual_bridge_tools(self) -> None:
        bridge = [_make_mock_tool("skill_select_tool", schema_size=200),
                  _make_mock_tool("discover_capability_tool", schema_size=100)]
        threshold = compute_direct_threshold(bridge_tools=bridge)
        expected = estimate_schema_tokens(bridge) * PTC_OVERHEAD_MULTIPLIER
        assert threshold == expected

    def test_multiplier_is_2(self) -> None:
        assert PTC_OVERHEAD_MULTIPLIER == 2

    def test_fallback_bridge_tokens_is_450(self) -> None:
        assert FALLBACK_PTC_BRIDGE_TOKENS == 450

    def test_threshold_scales_with_bridge_complexity(self) -> None:
        small_bridge = [_make_mock_tool("b1", schema_size=50)]
        large_bridge = [_make_mock_tool("b1", schema_size=500),
                        _make_mock_tool("b2", schema_size=300)]
        t_small = compute_direct_threshold(bridge_tools=small_bridge)
        t_large = compute_direct_threshold(bridge_tools=large_bridge)
        assert t_large > t_small


class TestMCPConfigClean:
    """Verify MCPConfig no longer has invocation_mode or direct_tool_threshold fields."""

    def test_no_invocation_mode_field(self) -> None:
        cfg = MCPConfig(name="test", type="stdio", command="echo")
        assert not hasattr(cfg, "invocation_mode") or "invocation_mode" not in cfg.model_fields

    def test_no_direct_tool_threshold_field(self) -> None:
        cfg = MCPConfig(name="test", type="stdio", command="echo")
        assert not hasattr(cfg, "direct_tool_threshold") or "direct_tool_threshold" not in cfg.model_fields

    def test_ptc_config_projection_keeps_host_serial(self) -> None:
        cfg = MCPConfig(name="stateful-host", type="stdio", command="echo", host_serial=True)
        payload = _config_to_dict(cfg)
        assert payload["host_serial"] is True

    def test_ptc_config_projection_keeps_keepalive_interval(self) -> None:
        cfg = MCPConfig(
            name="remote-host",
            type="sse",
            url="https://example.com/sse",
            keepalive_interval=45,
        )
        payload = _config_to_dict(cfg)
        assert payload["keepalive_interval"] == 45


class TestNormalizeMcpResult:
    """Test MCPAgent._normalize_mcp_result handles all langchain_mcp_adapters formats."""

    def test_text_content_blocks(self) -> None:
        from myrm_agent_harness.toolkits.mcp.agent import MCPAgent

        result = ([{"type": "text", "text": "Hello world"}], None)
        assert MCPAgent._normalize_mcp_result(result) == "Hello world"

    def test_multiple_text_blocks(self) -> None:
        from myrm_agent_harness.toolkits.mcp.agent import MCPAgent

        result = ([{"type": "text", "text": "line1"}, {"type": "text", "text": "line2"}], None)
        assert MCPAgent._normalize_mcp_result(result) == "line1\nline2"

    def test_image_block_passthrough(self) -> None:
        from myrm_agent_harness.toolkits.mcp.agent import MCPAgent

        block = {"type": "image", "data": "base64..."}
        result = ([block], None)
        normalized = MCPAgent._normalize_mcp_result(result)
        assert isinstance(normalized, list)
        assert block in normalized

    def test_plain_string_passthrough(self) -> None:
        from myrm_agent_harness.toolkits.mcp.agent import MCPAgent

        assert MCPAgent._normalize_mcp_result("direct string") == "direct string"

    def test_tuple_with_string_content(self) -> None:
        from myrm_agent_harness.toolkits.mcp.agent import MCPAgent

        result = ("string content", {"artifact": True})
        assert MCPAgent._normalize_mcp_result(result) == "string content"

    def test_empty_blocks(self) -> None:
        from myrm_agent_harness.toolkits.mcp.agent import MCPAgent

        assert MCPAgent._normalize_mcp_result(([], None)) == ""

    def test_non_tuple_non_string(self) -> None:
        from myrm_agent_harness.toolkits.mcp.agent import MCPAgent

        assert MCPAgent._normalize_mcp_result(12345) == "12345"

    def test_mixed_content_blocks(self) -> None:
        """File blocks are degraded to text, so mixed text+file returns a plain string."""
        from myrm_agent_harness.toolkits.mcp.agent import MCPAgent

        blocks = [
            {"type": "text", "text": "ticket info"},
            {"type": "file", "uri": "file:///tmp/x"},
        ]
        result = MCPAgent._normalize_mcp_result((blocks, None))
        assert isinstance(result, str)
        assert "ticket info" in result
        assert "[file" in result

    def test_structured_content_appended(self) -> None:
        from myrm_agent_harness.toolkits.mcp.agent import MCPAgent

        artifact = {"structured_content": {"status": "ok", "count": 42}}
        result = MCPAgent._normalize_mcp_result(
            ([{"type": "text", "text": "done"}], artifact)
        )
        assert isinstance(result, str)
        assert "done" in result
        assert '"status": "ok"' in result

    def test_image_with_text_mixed(self) -> None:
        from myrm_agent_harness.toolkits.mcp.agent import MCPAgent

        blocks = [
            {"type": "text", "text": "screenshot taken"},
            {"type": "image", "base64": "iVBOR...", "mime_type": "image/png"},
        ]
        result = MCPAgent._normalize_mcp_result((blocks, None))
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["type"] == "text"
        assert result[1]["type"] == "image"

    def test_artifact_object_with_structured_content(self) -> None:
        from myrm_agent_harness.toolkits.mcp.agent import MCPAgent

        class FakeArtifact:
            structured_content: dict[str, str] = {"key": "value"}  # noqa: RUF012

        result = MCPAgent._normalize_mcp_result(
            ([{"type": "text", "text": "info"}], FakeArtifact())
        )
        assert isinstance(result, str)
        assert "info" in result
        assert '"key": "value"' in result

    def test_string_element_in_content_blocks(self) -> None:
        from myrm_agent_harness.toolkits.mcp.agent import MCPAgent

        result = MCPAgent._normalize_mcp_result(
            (["raw string block", {"type": "text", "text": "dict block"}], None)
        )
        assert isinstance(result, str)
        assert "raw string block" in result
        assert "dict block" in result

    def test_non_dict_non_str_element(self) -> None:
        from myrm_agent_harness.toolkits.mcp.agent import MCPAgent

        result = MCPAgent._normalize_mcp_result(([42, True], None))
        assert isinstance(result, str)
        assert "42" in result

    def test_text_block_with_none_text(self) -> None:
        from myrm_agent_harness.toolkits.mcp.agent import MCPAgent

        result = MCPAgent._normalize_mcp_result(
            ([{"type": "text", "text": None}], None)
        )
        assert isinstance(result, str)

    def test_multimodal_with_structured_content(self) -> None:
        from myrm_agent_harness.toolkits.mcp.agent import MCPAgent

        artifact = {"structured_content": {"rows": 5}}
        blocks = [
            {"type": "image", "base64": "abc123"},
            {"type": "text", "text": "caption"},
        ]
        result = MCPAgent._normalize_mcp_result((blocks, artifact))
        assert isinstance(result, list)
        assert len(result) == 3
        assert result[2]["type"] == "text"
        assert '"rows": 5' in result[2]["text"]

    def test_artifact_without_structured_content(self) -> None:
        from myrm_agent_harness.toolkits.mcp.agent import MCPAgent

        result = MCPAgent._normalize_mcp_result(
            ([{"type": "text", "text": "data"}], {"other_key": True})
        )
        assert isinstance(result, str)
        assert result == "data"

    def test_tuple_wrong_length_fallback(self) -> None:
        from myrm_agent_harness.toolkits.mcp.agent import MCPAgent

        result = MCPAgent._normalize_mcp_result((1, 2, 3))
        assert isinstance(result, str)
        assert result == "(1, 2, 3)"

    def test_content_blocks_not_list_not_str(self) -> None:
        from myrm_agent_harness.toolkits.mcp.agent import MCPAgent

        result = MCPAgent._normalize_mcp_result((42, None))
        assert isinstance(result, str)
        assert result == "(42, None)"

    def test_structured_content_does_not_mutate_original(self) -> None:
        from myrm_agent_harness.toolkits.mcp.agent import MCPAgent

        original_blocks = [{"type": "text", "text": "original"}]
        artifact = {"structured_content": {"added": True}}
        MCPAgent._normalize_mcp_result((original_blocks, artifact))
        assert len(original_blocks) == 1
