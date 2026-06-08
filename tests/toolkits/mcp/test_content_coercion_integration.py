"""Integration tests for MCP content block coercion pipeline.

Exercises the FULL pipeline from real ``mcp.types`` objects through
``langchain_mcp_adapters`` conversion into ``_coerce_content_block``
and ``_normalize_mcp_result`` — no mocking of conversion or coercion
logic.  Verifies that every MCP content type that can appear in
production is safely handled end-to-end.
"""

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.tools import StructuredTool
from langchain_mcp_adapters.tools import _convert_mcp_content_to_lc_block
from mcp.types import (
    ImageContent,
    ResourceLink,
    TextContent,
)

from myrm_agent_harness.toolkits.mcp.agent import MCPAgent
from myrm_agent_harness.toolkits.mcp.client import MCPServerConfigProtocol


class DummyConfig(MCPServerConfigProtocol):
    name: str = "test_server"
    connect_timeout: float = 1.0
    execute_timeout: float = 2.0
    tool_include: list[str] | None = None
    tool_exclude: list[str] | None = None

    @property
    def transport(self) -> str:
        return "stdio"

    @property
    def transport_kwargs(self) -> dict[str, Any]:
        return {}


def _make_tool(name: str = "tool") -> StructuredTool:
    return StructuredTool.from_function(
        func=lambda: "",
        name=name,
        description="test",
        coroutine=AsyncMock(return_value=""),
    )


class TestRealMcpTypesThroughPipeline:
    """End-to-end: real MCP types -> langchain_mcp_adapters -> coercion -> normalize."""

    def test_text_content_passthrough(self):
        """TextContent flows through unchanged."""
        lc_block = _convert_mcp_content_to_lc_block(
            TextContent(type="text", text="hello world")
        )
        coerced = MCPAgent._coerce_content_block(lc_block)
        assert coerced["type"] == "text"
        assert coerced["text"] == "hello world"

        result = MCPAgent._normalize_mcp_result(([lc_block], None))
        assert result == "hello world"

    def test_image_content_preserved_as_multimodal(self):
        """ImageContent with base64 produces a multimodal list result."""
        lc_block = _convert_mcp_content_to_lc_block(
            ImageContent(type="image", data="base64data", mimeType="image/png")
        )
        coerced = MCPAgent._coerce_content_block(lc_block)
        assert coerced["type"] == "image"
        assert coerced["base64"] == "base64data"

        result = MCPAgent._normalize_mcp_result(([lc_block], None))
        assert isinstance(result, list)
        assert any(b["type"] == "image" for b in result)

    def test_resource_link_degraded_to_text(self):
        """ResourceLink -> file block -> safely degraded to text."""
        lc_block = _convert_mcp_content_to_lc_block(
            ResourceLink(
                type="resource_link",
                uri="file:///tmp/report.csv",
                name="report",
                mimeType="text/csv",
            )
        )
        assert lc_block["type"] == "file", "langchain_mcp_adapters should produce file block"

        coerced = MCPAgent._coerce_content_block(lc_block)
        assert coerced["type"] == "text"
        assert "file:///tmp/report.csv" in coerced["text"]

        result = MCPAgent._normalize_mcp_result(([lc_block], None))
        assert isinstance(result, str)
        assert "file:///tmp/report.csv" in result

    def test_mixed_text_and_resource_link(self):
        """Mix of TextContent + ResourceLink: text survives, file degraded."""
        text_block = _convert_mcp_content_to_lc_block(
            TextContent(type="text", text="Here is the report:")
        )
        file_block = _convert_mcp_content_to_lc_block(
            ResourceLink(
                type="resource_link",
                uri="https://example.com/data.json",
                name="data",
                mimeType="application/json",
            )
        )
        result = MCPAgent._normalize_mcp_result(([text_block, file_block], None))
        assert isinstance(result, str)
        assert "Here is the report:" in result
        assert "https://example.com/data.json" in result

    def test_mixed_image_and_resource_link(self):
        """Image + ResourceLink: returns multimodal list, file becomes text."""
        img_block = _convert_mcp_content_to_lc_block(
            ImageContent(type="image", data="imgdata", mimeType="image/jpeg")
        )
        file_block = _convert_mcp_content_to_lc_block(
            ResourceLink(
                type="resource_link",
                uri="file:///a.pdf",
                name="a",
                mimeType="application/pdf",
            )
        )
        result = MCPAgent._normalize_mcp_result(([img_block, file_block], None))
        assert isinstance(result, list)
        types = {b["type"] for b in result}
        assert "image" in types
        assert "text" in types
        assert "file" not in types

    def test_structured_content_appended(self):
        """structuredContent from artifact is appended as JSON text."""
        text_block = _convert_mcp_content_to_lc_block(
            TextContent(type="text", text="summary")
        )
        artifact = {"structured_content": {"key": "value", "num": 42}}
        result = MCPAgent._normalize_mcp_result(([text_block], artifact))
        assert isinstance(result, str)
        assert "summary" in result
        assert '"key"' in result
        assert "42" in result


class TestAudioContentUpstreamFault:
    """Verify _timeout_wrapper catches AudioContent crash from adapters."""

    @pytest.mark.asyncio
    async def test_audio_content_returns_error_not_crash(self):
        """Simulates an MCP tool that returns AudioContent — adapters raise
        NotImplementedError, which _timeout_wrapper must catch."""
        from mcp.types import AudioContent

        async def _raise_not_impl(*a: object, **kw: object) -> None:
            raise NotImplementedError(
                "AudioContent conversion to LangChain content blocks is not yet supported."
            )

        tool = _make_tool("audio_tool")
        tool.coroutine = _raise_not_impl
        MCPAgent._wrap_tools_with_timeout([tool], timeout=5.0)

        result = await tool.coroutine()
        assert isinstance(result, str)
        assert "unsupported content" in result
        assert "audio_tool" in result

    @pytest.mark.asyncio
    async def test_unknown_type_value_error_caught(self):
        """Simulates ValueError from unknown MCP content type."""

        async def _raise_value_error(*a: object, **kw: object) -> None:
            raise ValueError("Unknown MCP content type: CustomWidget")

        tool = _make_tool("widget_tool")
        tool.coroutine = _raise_value_error
        MCPAgent._wrap_tools_with_timeout([tool], timeout=5.0)

        result = await tool.coroutine()
        assert isinstance(result, str)
        assert "unsupported content" in result
        assert "widget_tool" in result

    @pytest.mark.asyncio
    async def test_type_error_from_malformed_args(self):
        """TypeError from malformed tool args is caught gracefully."""

        async def _raise_type_error(*a: object, **kw: object) -> None:
            raise TypeError("expected str, got NoneType")

        tool = _make_tool("bad_args_tool")
        tool.coroutine = _raise_type_error
        MCPAgent._wrap_tools_with_timeout([tool], timeout=5.0)

        result = await tool.coroutine()
        assert isinstance(result, str)
        assert "unsupported content" in result

    @pytest.mark.asyncio
    async def test_runtime_error_still_propagates(self):
        """Non-caught exceptions must still propagate (not silently swallowed)."""

        async def _raise_runtime(*a: object, **kw: object) -> None:
            raise RuntimeError("network down")

        tool = _make_tool("net_tool")
        tool.coroutine = _raise_runtime
        MCPAgent._wrap_tools_with_timeout([tool], timeout=5.0)

        with pytest.raises(RuntimeError, match="network down"):
            await tool.coroutine()


class TestFullToolExecutionPipeline:
    """Verify _wrap_tools_with_timeout + _normalize_mcp_result together
    using real adapter output shapes (no mocking of coercion logic)."""

    @pytest.mark.asyncio
    async def test_tool_returning_resource_link_tuple(self):
        """Tool returns (content_blocks_with_file, artifact) — full pipeline."""
        file_lc = _convert_mcp_content_to_lc_block(
            ResourceLink(
                type="resource_link",
                uri="s3://bucket/key.csv",
                name="key",
                mimeType="text/csv",
            )
        )

        async def _mock_invoke(*a: object, **kw: object) -> tuple:
            return ([file_lc], None)

        tool = _make_tool("csv_tool")
        tool.coroutine = _mock_invoke
        MCPAgent._wrap_tools_with_timeout([tool], timeout=5.0)

        result = await tool.coroutine()
        assert isinstance(result, str)
        assert "s3://bucket/key.csv" in result
        assert "file" not in result.split(":")[0] or "[file:" in result

    @pytest.mark.asyncio
    async def test_tool_returning_text_tuple(self):
        """Tool returns (text_blocks, artifact) — plain string output."""
        text_lc = _convert_mcp_content_to_lc_block(
            TextContent(type="text", text="query result: 42")
        )

        async def _mock_invoke(*a: object, **kw: object) -> tuple:
            return ([text_lc], None)

        tool = _make_tool("query_tool")
        tool.coroutine = _mock_invoke
        MCPAgent._wrap_tools_with_timeout([tool], timeout=5.0)

        result = await tool.coroutine()
        assert isinstance(result, str)
        assert "query result: 42" in result

    @pytest.mark.asyncio
    async def test_tool_returning_image_tuple(self):
        """Tool returns (image_blocks, artifact) — multimodal list output."""
        img_lc = _convert_mcp_content_to_lc_block(
            ImageContent(type="image", data="chart_png_base64", mimeType="image/png")
        )

        async def _mock_invoke(*a: object, **kw: object) -> tuple:
            return ([img_lc], None)

        tool = _make_tool("chart_tool")
        tool.coroutine = _mock_invoke
        MCPAgent._wrap_tools_with_timeout([tool], timeout=5.0)

        result = await tool.coroutine()
        assert isinstance(result, list)
        assert result[0]["type"] == "image"

    @pytest.mark.asyncio
    async def test_tool_returning_mixed_types_tuple(self):
        """Tool returns text + file + image — file degraded, image preserved."""
        text_lc = _convert_mcp_content_to_lc_block(
            TextContent(type="text", text="Analysis complete")
        )
        file_lc = _convert_mcp_content_to_lc_block(
            ResourceLink(
                type="resource_link",
                uri="gs://bucket/report.pdf",
                name="report",
                mimeType="application/pdf",
            )
        )
        img_lc = _convert_mcp_content_to_lc_block(
            ImageContent(type="image", data="chart", mimeType="image/png")
        )

        async def _mock_invoke(*a: object, **kw: object) -> tuple:
            return ([text_lc, file_lc, img_lc], None)

        tool = _make_tool("report_tool")
        tool.coroutine = _mock_invoke
        MCPAgent._wrap_tools_with_timeout([tool], timeout=5.0)

        result = await tool.coroutine()
        assert isinstance(result, list)
        block_types = [b["type"] for b in result]
        assert "image" in block_types
        assert "file" not in block_types
        assert "text" in block_types

    @pytest.mark.asyncio
    async def test_tool_timeout_returns_error_string(self):
        """Slow tool returns readable timeout error."""

        async def _slow(*a: object, **kw: object) -> str:
            await asyncio.sleep(10)
            return "never"

        tool = _make_tool("slow_tool")
        tool.coroutine = _slow
        MCPAgent._wrap_tools_with_timeout([tool], timeout=0.1)

        result = await tool.coroutine()
        assert isinstance(result, str)
        assert "timed out" in result
        assert "slow_tool" in result
