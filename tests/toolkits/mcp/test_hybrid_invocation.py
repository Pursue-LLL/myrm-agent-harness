"""Tests for MCP Hybrid Invocation routing.

Verifies:
- estimate_schema_tokens correctly estimates token count from tool schemas
- Auto routing decision: ≤threshold → direct, >threshold → PTC
- normalize_mcp_result handles all MCP tool result formats
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from mcp.types import (
    CallToolResult,
    ImageContent,
    ResourceLink,
    TextContent,
)

from myrm_agent_harness.agent._factory.mcp_routing import (
    DIRECT_MCP_DESCRIPTION_SOFT_LIMIT,
    FALLBACK_PTC_OVERHEAD_TOKENS,
    PTC_OVERHEAD_MULTIPLIER,
    _compact_description,
    _compress_direct_tools,
    _config_to_dict,
    compute_direct_threshold,
    estimate_schema_tokens,
)
from myrm_agent_harness.toolkits.mcp.config import MCPConfig
from myrm_agent_harness.toolkits.mcp.result_processing import normalize_mcp_result


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


class TestDirectToolDescriptionCompaction:
    def test_compact_description_trims_verbose_text(self) -> None:
        long_text = "Line one. " + ("Very long detail. " * 50)
        compact = _compact_description(long_text)
        assert len(compact) <= DIRECT_MCP_DESCRIPTION_SOFT_LIMIT + 1
        assert compact.endswith(".")

    def test_compact_description_keeps_short_text(self) -> None:
        short_text = "Short MCP summary."
        assert _compact_description(short_text) == short_text

    def test_compress_direct_tools_updates_description(self) -> None:
        tool = _make_mock_tool("verbose", schema_size=2000)
        original = tool.description
        compressed = _compress_direct_tools([tool])[0]
        assert compressed.name == tool.name
        assert len(compressed.description) < len(original)

    def test_compress_direct_tools_avoids_in_place_mutation_without_model_copy(
        self,
    ) -> None:
        tool = _make_mock_tool("plain", schema_size=2000)
        tool.model_copy = None
        original = tool.description
        compressed = _compress_direct_tools([tool])[0]
        assert tool.description == original
        assert len(compressed.description) < len(original)


class TestDynamicThreshold:
    """Test compute_direct_threshold based on PTC skill-search overhead."""

    def test_fallback_without_overhead_tools(self) -> None:
        threshold = compute_direct_threshold()
        assert threshold == FALLBACK_PTC_OVERHEAD_TOKENS * PTC_OVERHEAD_MULTIPLIER

    def test_with_actual_overhead_tools(self) -> None:
        overhead = [
            _make_mock_tool("skill_select_tool", schema_size=200),
            _make_mock_tool("skill_search_tool", schema_size=100),
        ]
        threshold = compute_direct_threshold(ptc_overhead_tools=overhead)
        expected = estimate_schema_tokens(overhead) * PTC_OVERHEAD_MULTIPLIER
        assert threshold == expected

    def test_multiplier_is_2(self) -> None:
        assert PTC_OVERHEAD_MULTIPLIER == 2

    def test_fallback_overhead_tokens_is_450(self) -> None:
        assert FALLBACK_PTC_OVERHEAD_TOKENS == 450

    def test_threshold_scales_with_overhead_complexity(self) -> None:
        small_overhead = [_make_mock_tool("b1", schema_size=50)]
        large_overhead = [
            _make_mock_tool("b1", schema_size=500),
            _make_mock_tool("b2", schema_size=300),
        ]
        t_small = compute_direct_threshold(ptc_overhead_tools=small_overhead)
        t_large = compute_direct_threshold(ptc_overhead_tools=large_overhead)
        assert t_large > t_small


class TestMCPConfigClean:
    """Verify MCPConfig no longer has invocation_mode or direct_tool_threshold fields."""

    def test_no_invocation_mode_field(self) -> None:
        cfg = MCPConfig(name="test", type="stdio", command="echo")
        assert (
            not hasattr(cfg, "invocation_mode")
            or "invocation_mode" not in cfg.model_fields
        )

    def test_no_direct_tool_threshold_field(self) -> None:
        cfg = MCPConfig(name="test", type="stdio", command="echo")
        assert (
            not hasattr(cfg, "direct_tool_threshold")
            or "direct_tool_threshold" not in cfg.model_fields
        )

    def test_ptc_config_projection_keeps_host_serial(self) -> None:
        cfg = MCPConfig(
            name="stateful-host", type="stdio", command="echo", host_serial=True
        )
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
    """Test normalize_mcp_result handles all MCP tool result formats."""

    def test_text_content_blocks(self) -> None:
        result = CallToolResult(content=[TextContent(type="text", text="Hello world")])
        assert normalize_mcp_result(result) == "Hello world"

    def test_multiple_text_blocks(self) -> None:
        result = CallToolResult(
            content=[
                TextContent(type="text", text="line1"),
                TextContent(type="text", text="line2"),
            ]
        )
        assert normalize_mcp_result(result) == "line1\nline2"

    def test_image_block_passthrough(self) -> None:
        result = CallToolResult(
            content=[ImageContent(type="image", data="base64...", mime_type="image/png")]
        )
        normalized = normalize_mcp_result(result)
        assert isinstance(normalized, list)
        assert normalized[0]["type"] == "image"

    def test_plain_string_passthrough(self) -> None:
        assert normalize_mcp_result("direct string") == "direct string"

    def test_empty_blocks(self) -> None:
        assert normalize_mcp_result(CallToolResult(content=[])) == ""

    def test_non_tuple_non_string(self) -> None:
        assert normalize_mcp_result(12345) == "12345"

    def test_mixed_content_blocks(self) -> None:
        """File blocks are degraded to text, so mixed text+file returns a plain string."""
        result = CallToolResult(
            content=[
                TextContent(type="text", text="ticket info"),
                ResourceLink(
                    type="resource_link",
                    uri="file:///tmp/x",
                    name="x",
                    mime_type="text/plain",
                ),
            ]
        )
        normalized = normalize_mcp_result(result)
        assert isinstance(normalized, str)
        assert "ticket info" in normalized
        assert "[file" in normalized

    def test_structured_content_appended(self) -> None:
        result = CallToolResult(
            content=[TextContent(type="text", text="done")],
            structured_content={"status": "ok", "count": 42},
        )
        normalized = normalize_mcp_result(result)
        assert isinstance(normalized, str)
        assert "done" in normalized
        assert '"status": "ok"' in normalized

    def test_image_with_text_mixed(self) -> None:
        result = CallToolResult(
            content=[
                TextContent(type="text", text="screenshot taken"),
                ImageContent(type="image", data="iVBOR...", mime_type="image/png"),
            ]
        )
        normalized = normalize_mcp_result(result)
        assert isinstance(normalized, list)
        assert len(normalized) == 2
        assert normalized[0]["type"] == "text"
        assert normalized[1]["type"] == "image"

    def test_is_error_result(self) -> None:
        """is_error=True collapses to a single error string."""
        result = CallToolResult(
            content=[TextContent(type="text", text="invalid request")],
            is_error=True,
        )
        normalized = normalize_mcp_result(result)
        assert isinstance(normalized, str)
        assert "[MCP tool error]" in normalized
        assert "invalid request" in normalized

    def test_multimodal_with_structured_content(self) -> None:
        result = CallToolResult(
            content=[
                ImageContent(type="image", data="abc123", mime_type="image/png"),
                TextContent(type="text", text="caption"),
            ],
            structured_content={"rows": 5},
        )
        normalized = normalize_mcp_result(result)
        assert isinstance(normalized, list)
        assert len(normalized) == 3
        assert normalized[2]["type"] == "text"
        assert '"rows": 5' in normalized[2]["text"]

    def test_embedded_resource_text_passthrough(self) -> None:
        """EmbeddedResource with TextResourceContents passes through as text."""
        from mcp.types import EmbeddedResource, TextResourceContents

        result = CallToolResult(
            content=[
                EmbeddedResource(
                    type="resource",
                    resource=TextResourceContents(
                        uri="file:///tmp/log.txt",
                        text="log data",
                        mime_type="text/plain",
                    ),
                )
            ]
        )
        normalized = normalize_mcp_result(result)
        assert isinstance(normalized, str)
        assert "log data" in normalized

    def test_audio_block_degraded_to_marker(self) -> None:
        """AudioContent degrades to a short marker, not a base64 dump."""
        from mcp.types import AudioContent

        result = CallToolResult(
            content=[AudioContent(type="audio", data="audio_b64", mime_type="audio/mpeg")]
        )
        normalized = normalize_mcp_result(result)
        assert isinstance(normalized, str)
        assert "[audio content omitted]" in normalized

    def test_content_blocks_not_list_not_str(self) -> None:
        result = normalize_mcp_result(SimpleNamespace(content=42))
        assert isinstance(result, str)
        assert "content=42" in result

    def test_structured_content_does_not_mutate_original(self) -> None:
        original_blocks = [TextContent(type="text", text="original")]
        result = CallToolResult(
            content=original_blocks,
            structured_content={"added": True},
        )
        normalize_mcp_result(result)
        assert len(original_blocks) == 1
