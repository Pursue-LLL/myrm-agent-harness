"""Agent code search tool factory.

[INPUT]
langchain.tools::tool (POS: LangChain tool decorator)
pydantic::BaseModel, Field (POS: input validation)
myrm_agent_harness.toolkits.code_index::CodeIndexer (POS: code indexer)

[OUTPUT]
create_code_search_tool: Factory function producing a code_search agent tool

[POS]
Semantic code search tool for the agent. Wraps CodeIndexer to provide
hybrid FTS5+Vector search over workspace source code.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from langchain.tools import tool
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

    from myrm_agent_harness.toolkits.code_index.indexer import CodeIndexer

logger = logging.getLogger(__name__)

_MAX_RESULT_CHARS = 8000


class CodeSearchInput(BaseModel):
    """Input schema for code_search_tool."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(
        description=(
            "Natural language or keyword query to search the codebase. "
            "Examples: 'authentication handler', 'database connection pool', "
            "'class UserService', 'error retry logic'."
        ),
    )
    scope: str = Field(
        default="",
        description="Optional file path pattern to narrow search scope (e.g. 'src/api/').",
    )
    limit: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Maximum number of results to return.",
    )


def create_code_search_tool(indexer: CodeIndexer) -> BaseTool:
    """Create a code_search agent tool backed by a CodeIndexer.

    Args:
        indexer: Initialized CodeIndexer for the workspace.

    Returns:
        A LangChain BaseTool for semantic code search.
    """

    @tool(
        "code_search_tool",
        description=(
            "Search for code across the workspace using semantic and keyword matching. "
            "Finds functions, classes, methods, and code patterns by meaning, not just "
            "exact text. Use this before grep_tool when you need to find code by concept "
            "(e.g. 'authentication handler') rather than exact string match. "
            "Results include file paths, line numbers, symbol definitions, and code summaries."
        ),
        args_schema=CodeSearchInput,
    )
    async def code_search_func(
        query: str,
        scope: str = "",
        limit: int = 10,
        *,
        config: RunnableConfig,
    ) -> str:
        await indexer.ensure_indexed()

        results = await indexer.search(query, limit=limit)

        if scope:
            results = [r for r in results if str(r.get("file_path", "")).startswith(scope)]

        if not results:
            return f"No code matches found for '{query}'. Try using grep_tool for exact text search."

        output_parts: list[str] = []
        output_parts.append(f"Found {len(results)} code matches for '{query}':\n")

        total_chars = 0
        for i, r in enumerate(results, 1):
            entry = f"{i}. {r['file_path']}"
            if "line" in r:
                entry += f":{r['line']}"
            entry += f" ({r.get('language', 'unknown')}) [score: {r['score']}]"

            if "symbols" in r:
                entry += f"\n   Symbols: {r['symbols']}"

            if r.get("summary"):
                summary = str(r["summary"])[:200]
                entry += f"\n   Summary: {summary}"

            entry += "\n"
            total_chars += len(entry)
            if total_chars > _MAX_RESULT_CHARS:
                output_parts.append(f"... ({len(results) - i} more results truncated)")
                break
            output_parts.append(entry)

        stats = indexer.get_stats()
        output_parts.append(
            f"\n[Index: {stats['indexed_files']} files, {stats['indexed_symbols']} symbols]"
        )
        return "\n".join(output_parts)

    return code_search_func
