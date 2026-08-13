"""Integration tests for MCP content block coercion pipeline.

Exercises the coercion and normalization pipeline for MCP tool result
content blocks using the real SDK 2.x ``CallToolResult`` shape produced by
``tool_converter._invoke`` (which now passes the raw result through).  Verifies
that every MCP content type that can appear in production is safely handled
end-to-end through ``coerce_content_block`` and ``normalize_mcp_result``.

Uses MCP SDK v2 types directly.
"""

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest
from langchain_core.tools import StructuredTool
from mcp.types import (
    AudioContent,
    BlobResourceContents,
    CallToolResult,
    EmbeddedResource,
    ImageContent,
    ResourceLink,
    TextContent,
    TextResourceContents,
)

from myrm_agent_harness.toolkits.mcp.agent import MCPAgent
from myrm_agent_harness.toolkits.mcp.result_processing import normalize_mcp_result
from myrm_agent_harness.toolkits.mcp.tool_processing import wrap_tools_with_timeout


def _make_tool(name: str = "tool") -> StructuredTool:
    return StructuredTool.from_function(
        func=lambda: "",
        name=name,
        description="test",
        coroutine=AsyncMock(return_value=""),
    )


class TestCallToolResultNormalization:
    """Direct `_normalize_mcp_result` coverage over real `CallToolResult`."""

    def test_text_content_passthrough(self):
        """TextContent flows through unchanged."""
        result = normalize_mcp_result(
            CallToolResult(content=[TextContent(type="text", text="hello world")])
        )
        assert result == "hello world"

    def test_image_content_preserved_as_multimodal(self):
        """ImageContent with base64 produces a multimodal list result."""
        result = normalize_mcp_result(
            CallToolResult(
                content=[
                    ImageContent(type="image", data="base64data", mimeType="image/png")
                ]
            )
        )
        assert isinstance(result, list)
        assert any(b["type"] == "image" for b in result)

    def test_resource_link_degraded_to_text(self):
        """ResourceLink -> file block -> safely degraded to text."""
        result = normalize_mcp_result(
            CallToolResult(
                content=[
                    ResourceLink(
                        type="resource_link",
                        uri="file:///tmp/report.csv",
                        name="report",
                        mimeType="text/csv",
                    )
                ]
            )
        )
        assert isinstance(result, str)
        assert "file:///tmp/report.csv" in result

    def test_mixed_text_and_resource_link(self):
        """Mix of TextContent + ResourceLink: text survives, file degraded."""
        result = normalize_mcp_result(
            CallToolResult(
                content=[
                    TextContent(type="text", text="Here is the report:"),
                    ResourceLink(
                        type="resource_link",
                        uri="https://example.com/data.json",
                        name="data",
                        mimeType="application/json",
                    ),
                ]
            )
        )
        assert isinstance(result, str)
        assert "Here is the report:" in result
        assert "https://example.com/data.json" in result

    def test_mixed_image_and_resource_link(self):
        """Image + ResourceLink: returns multimodal list, file becomes text."""
        result = normalize_mcp_result(
            CallToolResult(
                content=[
                    ImageContent(type="image", data="imgdata", mimeType="image/jpeg"),
                    ResourceLink(
                        type="resource_link",
                        uri="file:///a.pdf",
                        name="a",
                        mimeType="application/pdf",
                    ),
                ]
            )
        )
        assert isinstance(result, list)
        types = {b["type"] for b in result}
        assert "image" in types
        assert "text" in types
        assert "file" not in types

    def test_structured_content_appended(self):
        """structuredContent (real wire camelCase) is appended as JSON text."""
        result = normalize_mcp_result(
            CallToolResult(
                content=[TextContent(type="text", text="summary")],
                structuredContent={"key": "value", "num": 42},
            )
        )
        assert isinstance(result, str)
        assert "summary" in result
        assert '"key"' in result
        assert "42" in result

    def test_snake_case_extra_fields_still_read(self):
        """Legacy snake_case kwargs (extra attrs) still read via the compat path."""
        result = normalize_mcp_result(
            CallToolResult(
                content=[TextContent(type="text", text="summary")],
                is_error=True,
                structured_content={"key": "value"},
            )
        )
        assert isinstance(result, str)
        assert "[MCP tool error]" in result
        assert '"key"' in result

    def test_is_error_collapses_to_error_string(self):
        """isError (real wire camelCase) collapses to a single error string."""
        result = normalize_mcp_result(
            CallToolResult(
                content=[TextContent(type="text", text="permission denied")],
                isError=True,
            )
        )
        assert isinstance(result, str)
        assert "[MCP tool error]" in result
        assert "permission denied" in result

    def test_is_error_with_empty_content(self):
        """isError=True with no text yields a bare error marker."""
        result = normalize_mcp_result(CallToolResult(content=[], isError=True))
        assert result == "[MCP tool error]"

    def test_embedded_resource_text_passthrough(self):
        """EmbeddedResource with TextResourceContents passes through as text."""
        result = normalize_mcp_result(
            CallToolResult(
                content=[
                    EmbeddedResource(
                        type="resource",
                        resource=TextResourceContents(
                            uri="file:///tmp/log.txt",
                            text="log data",
                            mimeType="text/plain",
                        ),
                    )
                ]
            )
        )
        assert isinstance(result, str)
        assert "log data" in result

    def test_embedded_resource_blob_degraded(self):
        """EmbeddedResource with non-image BlobResourceContents -> file -> degraded to text."""
        result = normalize_mcp_result(
            CallToolResult(
                content=[
                    EmbeddedResource(
                        type="resource",
                        resource=BlobResourceContents(
                            uri="file:///tmp/data.bin",
                            blob="binary_base64",
                            mimeType="application/octet-stream",
                        ),
                    )
                ]
            )
        )
        assert isinstance(result, str)

    def test_embedded_resource_image_blob_preserved(self):
        """EmbeddedResource with image/png BlobResourceContents -> image (valid passthrough)."""
        result = normalize_mcp_result(
            CallToolResult(
                content=[
                    EmbeddedResource(
                        type="resource",
                        resource=BlobResourceContents(
                            uri="file:///tmp/photo.png",
                            blob="img_base64_data",
                            mimeType="image/png",
                        ),
                    )
                ]
            )
        )
        assert isinstance(result, list)
        assert any(b["type"] == "image" for b in result)

    def test_audio_content_degraded_to_text_marker(self):
        """AudioContent degrades to a short text marker, not a base64 dump."""
        result = normalize_mcp_result(
            CallToolResult(
                content=[
                    AudioContent(type="audio", data="audio_b64", mimeType="audio/mpeg")
                ]
            )
        )
        assert isinstance(result, str)
        assert "[audio content omitted]" in result
        assert "audio_b64" not in result

    def test_empty_content_blocks(self):
        """Empty content blocks list returns empty string."""
        result = normalize_mcp_result(CallToolResult(content=[]))
        assert isinstance(result, str)
        assert result == ""

    def test_multiple_file_blocks_all_degraded(self):
        """Multiple ResourceLink file blocks all degrade to text."""
        result = normalize_mcp_result(
            CallToolResult(
                content=[
                    ResourceLink(
                        type="resource_link",
                        uri=f"s3://bucket/file{i}.csv",
                        name=f"file{i}",
                        mimeType="text/csv",
                    )
                    for i in range(3)
                ]
            )
        )
        assert isinstance(result, str)
        assert "file" not in result or "[file:" in result
        for i in range(3):
            assert f"s3://bucket/file{i}.csv" in result

    def test_multiple_text_blocks_joined(self):
        """Multiple text blocks are joined with newline separator."""
        result = normalize_mcp_result(
            CallToolResult(
                content=[TextContent(type="text", text=f"line {i}") for i in range(3)]
            )
        )
        assert isinstance(result, str)
        assert "line 0" in result
        assert "line 1" in result
        assert "line 2" in result

    def test_plain_string_passthrough(self):
        """A raw string (timeout/auth message) returns unchanged."""
        assert normalize_mcp_result("already rendered") == "already rendered"

    def test_non_list_content_falls_back_to_str(self):
        """A result without a list content falls back to str()."""
        result = normalize_mcp_result(object())
        assert isinstance(result, str)


class TestAudioContentUpstreamFault:
    """Verify _timeout_wrapper catches AudioContent crash from adapters."""

    @pytest.mark.asyncio
    async def test_audio_content_returns_error_not_crash(self):
        """Simulates an MCP tool that returns AudioContent — adapters raise
        NotImplementedError, which _timeout_wrapper must catch."""

        async def _raise_not_impl(*a: object, **kw: object) -> None:
            raise NotImplementedError(
                "AudioContent conversion to LangChain content blocks is not yet supported."
            )

        tool = _make_tool("audio_tool")
        tool.coroutine = _raise_not_impl
        wrap_tools_with_timeout([tool], timeout=5.0)

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
        wrap_tools_with_timeout([tool], timeout=5.0)

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
        wrap_tools_with_timeout([tool], timeout=5.0)

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
        wrap_tools_with_timeout([tool], timeout=5.0)

        with pytest.raises(RuntimeError, match="network down"):
            await tool.coroutine()


class TestFullToolExecutionPipeline:
    """Verify _wrap_tools_with_timeout + _normalize_mcp_result together
    using the real CallToolResult shape (no mocked coercion logic)."""

    @pytest.mark.asyncio
    async def test_tool_returning_resource_link_result(self):
        """Tool returns CallToolResult with file block — full pipeline."""

        async def _mock_invoke(*a: object, **kw: object) -> CallToolResult:
            return CallToolResult(
                content=[
                    ResourceLink(
                        type="resource_link",
                        uri="s3://bucket/key.csv",
                        name="key",
                        mimeType="text/csv",
                    )
                ]
            )

        tool = _make_tool("csv_tool")
        tool.coroutine = _mock_invoke
        wrap_tools_with_timeout([tool], timeout=5.0)

        result = await tool.coroutine()
        assert isinstance(result, str)
        assert "s3://bucket/key.csv" in result
        assert "file" not in result.split(":")[0] or "[file:" in result

    @pytest.mark.asyncio
    async def test_tool_returning_text_result(self):
        """Tool returns CallToolResult with text block — plain string output."""

        async def _mock_invoke(*a: object, **kw: object) -> CallToolResult:
            return CallToolResult(
                content=[TextContent(type="text", text="query result: 42")]
            )

        tool = _make_tool("query_tool")
        tool.coroutine = _mock_invoke
        wrap_tools_with_timeout([tool], timeout=5.0)

        result = await tool.coroutine()
        assert isinstance(result, str)
        assert "query result: 42" in result

    @pytest.mark.asyncio
    async def test_tool_returning_image_result(self):
        """Tool returns CallToolResult with image block — multimodal list output."""

        async def _mock_invoke(*a: object, **kw: object) -> CallToolResult:
            return CallToolResult(
                content=[
                    ImageContent(
                        type="image", data="chart_png_base64", mimeType="image/png"
                    )
                ]
            )

        tool = _make_tool("chart_tool")
        tool.coroutine = _mock_invoke
        wrap_tools_with_timeout([tool], timeout=5.0)

        result = await tool.coroutine()
        assert isinstance(result, list)
        assert result[0]["type"] == "image"

    @pytest.mark.asyncio
    async def test_tool_returning_mixed_types_result(self):
        """Text + file + image: file degraded, image preserved."""

        async def _mock_invoke(*a: object, **kw: object) -> CallToolResult:
            return CallToolResult(
                content=[
                    TextContent(type="text", text="Analysis complete"),
                    ResourceLink(
                        type="resource_link",
                        uri="gs://bucket/report.pdf",
                        name="report",
                        mimeType="application/pdf",
                    ),
                    ImageContent(type="image", data="chart", mimeType="image/png"),
                ]
            )

        tool = _make_tool("report_tool")
        tool.coroutine = _mock_invoke
        wrap_tools_with_timeout([tool], timeout=5.0)

        result = await tool.coroutine()
        assert isinstance(result, list)
        block_types = [b["type"] for b in result]
        assert "image" in block_types
        assert "file" not in block_types
        assert "text" in block_types

    @pytest.mark.asyncio
    async def test_tool_returning_is_error_result(self):
        """Tool returns CallToolResult with isError=True — error string output."""

        async def _mock_invoke(*a: object, **kw: object) -> CallToolResult:
            return CallToolResult(
                content=[TextContent(type="text", text="rate limited")],
                isError=True,
            )

        tool = _make_tool("limited_tool")
        tool.coroutine = _mock_invoke
        wrap_tools_with_timeout([tool], timeout=5.0)

        result = await tool.coroutine()
        assert isinstance(result, str)
        assert "[MCP tool error]" in result
        assert "rate limited" in result

    @pytest.mark.asyncio
    async def test_tool_timeout_returns_error_string(self):
        """Slow tool returns readable timeout error."""

        async def _slow(*a: object, **kw: object) -> str:
            await asyncio.sleep(10)
            return "never"

        tool = _make_tool("slow_tool")
        tool.coroutine = _slow
        wrap_tools_with_timeout([tool], timeout=0.1)

        result = await tool.coroutine()
        assert isinstance(result, str)
        assert "timed out" in result
        assert "slow_tool" in result

    @pytest.mark.asyncio
    async def test_tool_returning_embedded_resource_blob(self):
        """EmbeddedResource non-image blob -> file -> degraded to text."""

        async def _mock_invoke(*a: object, **kw: object) -> CallToolResult:
            return CallToolResult(
                content=[
                    EmbeddedResource(
                        type="resource",
                        resource=BlobResourceContents(
                            uri="file:///tmp/archive.zip",
                            blob="zip_base64",
                            mimeType="application/zip",
                        ),
                    )
                ]
            )

        tool = _make_tool("archive_tool")
        tool.coroutine = _mock_invoke
        wrap_tools_with_timeout([tool], timeout=5.0)

        result = await tool.coroutine()
        assert isinstance(result, str)
        assert "file" not in result.split(":")[0] or "[file" in result

    @pytest.mark.asyncio
    async def test_tool_returning_plain_string(self):
        """Tool returns a plain string — wrapped with security boundary."""

        async def _mock_invoke(*a: object, **kw: object) -> str:
            return "simple response"

        tool = _make_tool("simple_tool")
        tool.coroutine = _mock_invoke
        wrap_tools_with_timeout([tool], timeout=5.0)

        result = await tool.coroutine()
        assert isinstance(result, str)
        assert "simple response" in result
        assert "UNTRUSTED_DATA" in result

    @pytest.mark.asyncio
    async def test_tool_returning_empty_content(self):
        """Tool returns CallToolResult with empty content — empty string output."""

        async def _mock_invoke(*a: object, **kw: object) -> CallToolResult:
            return CallToolResult(content=[])

        tool = _make_tool("empty_tool")
        tool.coroutine = _mock_invoke
        wrap_tools_with_timeout([tool], timeout=5.0)

        result = await tool.coroutine()
        assert isinstance(result, str)
        assert result == ""


class TestProcessSessionToolsChain:
    """Verify the full process_session_tools pipeline applies coercion."""

    @pytest.mark.asyncio
    async def test_full_chain_applies_coercion(self):
        """process_session_tools -> _wrap_tools_with_timeout -> coercion active."""

        async def _mock_invoke(*a: object, **kw: object) -> CallToolResult:
            return CallToolResult(
                content=[
                    ResourceLink(
                        type="resource_link",
                        uri="https://cdn.example.com/doc.pdf",
                        name="doc",
                        mimeType="application/pdf",
                    )
                ]
            )

        tool = _make_tool("doc_tool")
        tool.coroutine = _mock_invoke

        processed = MCPAgent.process_session_tools(
            [tool],
            server_name="test_server",
            tool_include=None,
            tool_exclude=None,
            execute_timeout=5.0,
        )
        assert len(processed) == 1
        assert processed[0].name.startswith("mcp__")

        result = await processed[0].coroutine()
        assert isinstance(result, str)
        assert "https://cdn.example.com/doc.pdf" in result

    @pytest.mark.asyncio
    async def test_full_chain_preserves_image(self):
        """process_session_tools preserves image blocks in multimodal output."""

        async def _mock_invoke(*a: object, **kw: object) -> CallToolResult:
            return CallToolResult(
                content=[
                    ImageContent(
                        type="image", data="screenshot_b64", mimeType="image/png"
                    )
                ]
            )

        tool = _make_tool("screenshot_tool")
        tool.coroutine = _mock_invoke

        processed = MCPAgent.process_session_tools(
            [tool],
            server_name="browser",
            tool_include=None,
            tool_exclude=None,
            execute_timeout=5.0,
        )
        result = await processed[0].coroutine()
        assert isinstance(result, list)
        assert result[0]["type"] == "image"

    @pytest.mark.asyncio
    async def test_full_chain_mixed_union_container_literal_coercion(self):
        """Mixed union payload should parse clear JSON object literals end-to-end."""
        seen_kwargs: dict[str, Any] = {}

        async def _capture(*a: object, **kw: object) -> str:
            seen_kwargs.update(kw)
            return "ok"

        tool = StructuredTool(
            name="mixed_union_tool",
            description="mixed union e2e",
            args_schema={
                "type": "object",
                "properties": {
                    "payload": {
                        "anyOf": [
                            {"type": "string"},
                            {"type": "object"},
                            {"type": "null"},
                        ]
                    }
                },
            },
            coroutine=_capture,
        )

        processed = MCPAgent.process_session_tools(
            [tool],
            server_name="mixed_server",
            tool_include=None,
            tool_exclude=None,
            execute_timeout=5.0,
        )
        result = await processed[0].coroutine(payload='{"x": 1}')
        assert isinstance(result, str)
        assert "ok" in result
        assert seen_kwargs["payload"] == {"x": 1}

    @pytest.mark.asyncio
    async def test_full_chain_mixed_union_plain_string_passthrough(self):
        """Mixed union payload should preserve plain text end-to-end."""
        seen_kwargs: dict[str, Any] = {}

        async def _capture(*a: object, **kw: object) -> str:
            seen_kwargs.update(kw)
            return "ok"

        tool = StructuredTool(
            name="mixed_union_text_tool",
            description="mixed union text e2e",
            args_schema={
                "type": "object",
                "properties": {
                    "payload": {
                        "anyOf": [
                            {"type": "string"},
                            {"type": "object"},
                            {"type": "null"},
                        ]
                    }
                },
            },
            coroutine=_capture,
        )

        processed = MCPAgent.process_session_tools(
            [tool],
            server_name="mixed_server",
            tool_include=None,
            tool_exclude=None,
            execute_timeout=5.0,
        )
        result = await processed[0].coroutine(payload="hello world")
        assert isinstance(result, str)
        assert "ok" in result
        assert seen_kwargs["payload"] == "hello world"

    @pytest.mark.asyncio
    async def test_full_chain_required_nullable_true_injects_missing_none(self):
        """Missing required nullable:true argument should be injected as None."""
        seen_kwargs: dict[str, Any] = {}

        async def _capture(*a: object, **kw: object) -> str:
            seen_kwargs.update(kw)
            return "ok"

        tool = StructuredTool(
            name="nullable_inject_tool",
            description="nullable inject e2e",
            args_schema={
                "type": "object",
                "required": ["optional_flag"],
                "properties": {
                    "optional_flag": {
                        "type": "string",
                        "nullable": True,
                    }
                },
            },
            coroutine=_capture,
        )

        processed = MCPAgent.process_session_tools(
            [tool],
            server_name="mixed_server",
            tool_include=None,
            tool_exclude=None,
            execute_timeout=5.0,
        )
        result = await processed[0].coroutine()
        assert isinstance(result, str)
        assert "ok" in result
