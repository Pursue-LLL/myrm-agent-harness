"""Unit tests for the wiki MCP server adapter (external-agent surface).

Covers: L1 contract drift guard (MCP shell params must cover the LangChain
tool params), the local-path refusal security narrowing for ingest, request
scoping ContextVar, and forwarding behavior for all three tools.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.tools import BaseTool
from mcp.server.mcpserver import MCPServer
from mcp.types import TextContent

from myrm_agent_harness.toolkits.wiki import create_wiki_agent_tools
from myrm_agent_harness.toolkits.wiki import mcp_server as wiki_mcp
from myrm_agent_harness.toolkits.wiki.mcp_server import (
    _looks_like_local_path,
    get_request_wiki_tools,
    register_wiki_mcp_tools,
    reset_request_wiki_tools,
    set_request_wiki_tools,
)


def _build_langchain_tools() -> list[BaseTool]:
    """Build the real LangChain wiki tools with mock engines.

    create_wiki_agent_tools only closes over its engine arguments, so
    MagicMock engines yield genuine tools whose arg schemas match production.
    """
    return create_wiki_agent_tools(
        MagicMock(name="compiler"),
        MagicMock(name="query_engine"),
        MagicMock(name="structure"),
    )


async def _mcp_tool_schemas() -> dict[str, set[str]]:
    mcp = MCPServer("test-wiki")
    register_wiki_mcp_tools(mcp, get_request_wiki_tools)
    tools = await mcp.list_tools()
    return {
        t.name: set((t.input_schema or {}).get("properties", {}).keys())
        for t in tools
        if t.name.startswith("wiki_")
    }


@pytest.mark.asyncio
async def test_mcp_tool_params_cover_langchain_tool_params() -> None:
    """L1 drift guard: MCP shell params must match the LangChain tool params.

    Mirrors the Hindsight pattern (test_trigger_input_covers_every_http_
    trigger_field): when wiki_agent_tools gains or renames a parameter, this
    test fails until the MCP shell is updated in lockstep.
    """
    langchain_params = {t.name: set(t.args.keys()) for t in _build_langchain_tools()}
    mcp_params = await _mcp_tool_schemas()

    assert set(langchain_params) == set(mcp_params), "tool name sets must match"
    for name, params in langchain_params.items():
        assert mcp_params[name] == params, (
            f"parameter drift for {name}: MCP has {mcp_params[name]}, "
            f"LangChain has {params}"
        )


@pytest.mark.asyncio
async def test_register_wiki_mcp_tools_registers_three_tools() -> None:
    mcp = MCPServer("test-wiki")
    register_wiki_mcp_tools(mcp, get_request_wiki_tools)
    tools = await mcp.list_tools()
    wiki_names = {t.name for t in tools if t.name.startswith("wiki_")}
    assert wiki_names == {"wiki_query_tool", "wiki_ingest_tool", "wiki_apply_tool"}


def test_request_wiki_tools_context() -> None:
    """Test set, get, and reset of the request-scoped wiki tool bundle."""
    assert get_request_wiki_tools() is None

    mock_tools = {"wiki_query_tool": MagicMock()}
    token = set_request_wiki_tools(mock_tools)
    try:
        assert get_request_wiki_tools() is mock_tools
    finally:
        reset_request_wiki_tools(token)

    assert get_request_wiki_tools() is None


def test_looks_like_local_path_branch_conditions(tmp_path: Path) -> None:
    """The refusal condition must mirror the LangChain ingest local-file branch."""
    local_file = tmp_path / "notes.md"
    local_file.write_text("hello", encoding="utf-8")

    assert _looks_like_local_path(str(local_file)) is True
    assert _looks_like_local_path("https://example.com/doc") is False
    assert _looks_like_local_path("http://example.com/doc") is False
    # Long raw text (>260 chars) is raw text, not a path.
    assert _looks_like_local_path("word " * 100) is False
    # Multiline raw text is raw text, not a path.
    assert _looks_like_local_path("line one\nline two") is False
    # Short non-existent string is raw text on the LangChain branch too.
    assert _looks_like_local_path("just some notes") is False


@pytest.mark.asyncio
async def test_wiki_tools_unavailable_when_resolver_returns_none() -> None:
    """When wiki is not enabled for the agent, the tool refuses cleanly."""
    mcp = MCPServer("test-wiki")
    register_wiki_mcp_tools(mcp, lambda: None)
    tools = await mcp.list_tools()
    assert any(t.name == "wiki_query_tool" for t in tools)

    result = await mcp.call_tool("wiki_query_tool", {"question": "any question"})
    contents = result[0] if isinstance(result, list) else result.content
    text = contents[0].text if isinstance(contents, list) else str(contents)
    assert "not available" in text


def _bundle_with_mocks() -> dict[str, BaseTool]:
    """Bundle of mock LangChain tools that record ainvoke calls."""
    bundle: dict[str, BaseTool] = {}
    for name in ("wiki_query_tool", "wiki_ingest_tool", "wiki_apply_tool"):
        tool = MagicMock(name=name)
        tool.name = name
        tool.ainvoke = AsyncMock(return_value=f"{name} ok")
        bundle[name] = tool
    return bundle


@pytest.mark.asyncio
async def test_wiki_query_forwards_to_langchain_tool() -> None:
    bundle = _bundle_with_mocks()
    mcp = MCPServer("test-wiki")
    register_wiki_mcp_tools(mcp, lambda: bundle)

    await mcp.call_tool("wiki_query_tool", {"question": "What is X?"})

    bundle["wiki_query_tool"].ainvoke.assert_awaited_once_with({"question": "What is X?"})


@pytest.mark.asyncio
async def test_wiki_ingest_forwards_url_and_raw_text() -> None:
    bundle = _bundle_with_mocks()
    mcp = MCPServer("test-wiki")
    register_wiki_mcp_tools(mcp, lambda: bundle)

    await mcp.call_tool(
        "wiki_ingest_tool",
        {"source": "https://example.com/doc", "filename": "doc.md", "folder_path": "Research"},
    )
    await mcp.call_tool("wiki_ingest_tool", {"source": "plain notes"})

    assert bundle["wiki_ingest_tool"].ainvoke.await_count == 2


@pytest.mark.asyncio
async def test_wiki_ingest_refuses_local_file_paths(tmp_path: Path) -> None:
    """Security narrowing: MCP ingest must never read server-side local files."""
    bundle = _bundle_with_mocks()
    mcp = MCPServer("test-wiki")
    register_wiki_mcp_tools(mcp, lambda: bundle)

    secret = tmp_path / "secret.md"
    secret.write_text("server-side secret", encoding="utf-8")

    result = await mcp.call_tool("wiki_ingest_tool", {"source": str(secret)})

    bundle["wiki_ingest_tool"].ainvoke.assert_not_awaited()
    contents = result[0] if isinstance(result, list) else result.content
    text = contents[0].text if isinstance(contents, list) else str(contents)
    assert "local file paths are not supported" in text


@pytest.mark.asyncio
async def test_wiki_apply_forwards_to_langchain_tool() -> None:
    bundle = _bundle_with_mocks()
    mcp = MCPServer("test-wiki")
    register_wiki_mcp_tools(mcp, lambda: bundle)

    await mcp.call_tool(
        "wiki_apply_tool",
        {
            "op": "create_note",
            "concept_name": "research/topic",
            "body": "note body",
            "tags": "a,b",
        },
    )

    bundle["wiki_apply_tool"].ainvoke.assert_awaited_once_with(
        {
            "op": "create_note",
            "concept_name": "research/topic",
            "compiled_truth": "",
            "timeline_entry": "",
            "body": "note body",
            "tags": "a,b",
            "aliases": "",
            "sources": "",
            "clear_confidence": False,
        }
    )


def _to_text_content(result: object) -> list[TextContent]:
    return wiki_mcp._to_text_content(result)


def test_tool_result_dict_uses_content_field() -> None:
    """wiki_query returns {"content": ..., "metadata": ...}; MCP uses content."""
    result = _to_text_content({"content": "answer text", "metadata": {"sources": []}})
    assert len(result) == 1
    assert result[0].text == "answer text"


def test_tool_result_string_passthrough() -> None:
    result = _to_text_content("plain string")
    assert len(result) == 1
    assert result[0].text == "plain string"
