"""Wiki MCP Server Adapter.

Exposes the wiki knowledge base tools (wiki_query_tool, wiki_ingest_tool,
wiki_apply_tool) to external agents (Claude Code, Cursor, etc.) via the
Model Context Protocol.

[INPUT]
- toolkits.wiki.wiki_agent_tools::create_wiki_agent_tools (POS: LangChain wiki tool factory — the single engine-level implementation of ingest/query/apply)
- mcp.server.mcpserver::MCPServer (POS: MCP SDK server to attach tools to)
- langchain_core.tools::BaseTool (POS: LangChain tool interface — invoked via ainvoke so this adapter holds zero engine logic)

[OUTPUT]
- register_wiki_mcp_tools: attach wiki_query/wiki_ingest/wiki_apply MCP tools to any MCPServer
- set_request_wiki_tools / reset_request_wiki_tools / get_request_wiki_tools: Request-level scoping

[POS]
MCP server adapter for the wiki toolkit. Thin shell over the LangChain tools
(single source of truth — parameter parsing, security hooks, and pipelines all
live in wiki_agent_tools; this adapter only forwards and formats). Ingest on
this surface accepts URLs and raw text only: local file paths are a
trusted-surface capability and are refused for remote callers.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextvars import ContextVar, Token
from pathlib import Path

from langchain_core.tools import BaseTool
from mcp.server.mcpserver import MCPServer
from mcp.types import TextContent

logger = logging.getLogger(__name__)

# Name → tool bundle for the current request. Built by the server layer via
# create_wiki_agent_tools() so engine construction (LLM, structure, scope)
# stays in the owning layer; this adapter only consumes finished tools.
_request_wiki_tools: ContextVar[dict[str, BaseTool] | None] = ContextVar(
    "myrm_mcp_request_wiki_tools",
    default=None,
)

WikiToolsResolver = Callable[[], dict[str, BaseTool] | None]

_WIKI_UNAVAILABLE_MESSAGE = "Error: Wiki knowledge base is not available in the current context."
_LOCAL_PATH_REFUSED_MESSAGE = (
    "Rejected: local file paths are not supported on the MCP surface. "
    "Pass the document content as raw text, or a public URL instead."
)


def set_request_wiki_tools(
    tools: dict[str, BaseTool] | None,
) -> Token[dict[str, BaseTool] | None]:
    """Bind the wiki tool bundle used by MCP wiki tool handlers for the current request."""
    return _request_wiki_tools.set(tools)


def reset_request_wiki_tools(token: Token[dict[str, BaseTool] | None]) -> None:
    """Restore the previous wiki tool bundle binding after a request completes."""
    _request_wiki_tools.reset(token)


def get_request_wiki_tools() -> dict[str, BaseTool] | None:
    """Return the active wiki tool bundle for the current MCP request context."""
    return _request_wiki_tools.get()


def _looks_like_local_path(source: str) -> bool:
    """Mirror the local-file branch condition of wiki_ingest (wiki_agent_tools).

    Must stay in sync with the LangChain tool's path detection so the refusal
    covers exactly the branch it is meant to block. L1 contract test
    (tests/toolkits/wiki/test_wiki_mcp_server.py) fails if the two drift apart.
    """
    if source.startswith(("http://", "https://")):
        return False
    return len(source) < 260 and "\n" not in source and Path(source).exists()


def _to_text_content(result: object) -> list[TextContent]:
    """Convert a LangChain tool result (str or content/metadata dict) to MCP text."""
    if isinstance(result, dict):
        # wiki_query returns {"content": ..., "metadata": sources-for-Chat-UI};
        # the evidence cards are already embedded in content for external agents.
        text = str(result.get("content", ""))
    else:
        text = str(result)
    return [TextContent(type="text", text=text)]


async def _invoke_tool(
    tools: dict[str, BaseTool],
    name: str,
    args: dict[str, object],
) -> list[TextContent]:
    tool = tools[name]
    result = await tool.ainvoke(args)
    return _to_text_content(result)


def register_wiki_mcp_tools(
    mcp: MCPServer,
    tools_resolver: WikiToolsResolver,
) -> None:
    """Register wiki knowledge base tools on an existing MCPServer instance.

    Args:
        mcp: The MCPServer on which to register wiki tools.
        tools_resolver: Callable returning the name→tool bundle for the current
            request context (None when wiki is not enabled for that agent).
    """

    @mcp.tool(
        name="wiki_query_tool",
        description=(
            "Query the Wiki knowledge base.\n\n"
            "Searches compiled wiki articles and returns grounded context with "
            "source citations. Search here first when answering questions about "
            "project concepts, domain knowledge, team notes, or compiled research. "
            "When the tool refuses (insufficient evidence), tell the user honestly "
            "that the knowledge base has no verified basis for the question — "
            "never guess or invent an answer."
        ),
    )
    async def wiki_query(question: str) -> list[TextContent]:
        tools = tools_resolver()
        if tools is None:
            return [TextContent(type="text", text=_WIKI_UNAVAILABLE_MESSAGE)]
        return await _invoke_tool(tools, "wiki_query_tool", {"question": question})

    @mcp.tool(
        name="wiki_ingest_tool",
        description=(
            "Ingest a document into the Wiki knowledge base for compilation.\n\n"
            "Supported inputs on this surface: public Web URLs (fetched and "
            "converted to markdown) or raw text content. Local file paths are "
            "not supported here — read the file first and pass its content as "
            "raw text. Use folder_path to categorize the document (e.g. "
            "'Research/AI'). Ingestion queues the document for knowledge "
            "compilation automatically."
        ),
    )
    async def wiki_ingest(
        source: str,
        filename: str = "",
        folder_path: str = "",
    ) -> list[TextContent]:
        tools = tools_resolver()
        if tools is None:
            return [TextContent(type="text", text=_WIKI_UNAVAILABLE_MESSAGE)]
        # Trusted-surface narrowing: the LangChain tool also accepts local file
        # paths (trusted for in-process agents); remote MCP callers must not
        # read arbitrary server-side files through the wiki pipeline.
        if _looks_like_local_path(source):
            return [TextContent(type="text", text=_LOCAL_PATH_REFUSED_MESSAGE)]
        return await _invoke_tool(
            tools,
            "wiki_ingest_tool",
            {"source": source, "filename": filename, "folder_path": folder_path},
        )

    @mcp.tool(
        name="wiki_apply_tool",
        description=(
            "Apply a narrow, structured mutation to a wiki concept page.\n\n"
            "Protects managed sections. Writes are staged as pending drafts for "
            "human review in the WebUI and publish only after approval; report "
            "the note as awaiting review, not published. Pick the smallest op "
            "that fits: create_note, patch_compiled_truth, append_timeline, "
            "update_metadata."
        ),
    )
    async def wiki_apply(
        op: str,
        concept_name: str,
        compiled_truth: str = "",
        timeline_entry: str = "",
        body: str = "",
        tags: str = "",
        aliases: str = "",
        sources: str = "",
        clear_confidence: bool = False,
    ) -> list[TextContent]:
        tools = tools_resolver()
        if tools is None:
            return [TextContent(type="text", text=_WIKI_UNAVAILABLE_MESSAGE)]
        return await _invoke_tool(
            tools,
            "wiki_apply_tool",
            {
                "op": op,
                "concept_name": concept_name,
                "compiled_truth": compiled_truth,
                "timeline_entry": timeline_entry,
                "body": body,
                "tags": tags,
                "aliases": aliases,
                "sources": sources,
                "clear_confidence": clear_confidence,
            },
        )


__all__ = [
    "get_request_wiki_tools",
    "register_wiki_mcp_tools",
    "reset_request_wiki_tools",
    "set_request_wiki_tools",
]
