"""LangChain tools for local file search toolkit.

[INPUT]
- langchain_core.tools::tool (POS: LangChain tool decorator)
- .search::LocalFileSearchEngine (POS: search engine)
- .indexer::LocalFileIndexer (POS: indexing engine)

[OUTPUT]
- create_local_file_search_tools(): creates LangChain tools for Agent use

[POS]
LangChain tool integration layer. Wraps LocalFileSearchEngine and LocalFileIndexer
into structured tools for Agent use. The search tool is the primary interface;
index status is informational.
"""

from __future__ import annotations

from typing import Annotated

from langchain_core.tools import tool

from myrm_agent_harness.utils.logger_utils import get_agent_logger

from .indexer import LocalFileIndexer
from .search import LocalFileSearchEngine

logger = get_agent_logger(__name__)


def create_local_file_search_tools(
    search_engine: LocalFileSearchEngine,
    indexer: LocalFileIndexer,
) -> list:
    """Create local file search tools for Agent use.

    Args:
        search_engine: Initialized LocalFileSearchEngine
        indexer: Initialized LocalFileIndexer

    Returns:
        List of LangChain tools
    """

    @tool("search_local_files_tool")
    async def search_local_files(
        query: Annotated[str, "Natural language search query describing what you are looking for"],
        top_k: Annotated[int, "Maximum number of results to return (1-50)"] = 10,
        file_type: Annotated[str, "Optional: filter by file type extension, e.g. 'pdf', 'docx', 'md'"] = "",
    ) -> str:
        """Search through the user's locally indexed files using semantic search.

        This tool searches documents that the user has explicitly authorized for indexing.
        It finds relevant content based on meaning, not just keyword matching.

        Supported file types: PDF, Word, Excel, PowerPoint, Markdown, plain text, code files, and more.

        Use this when the user asks to:
        - Find specific information in their local documents
        - Search for files containing certain topics or concepts
        - Look up content across their document collection

        The search uses semantic understanding, so queries like "contract renewal terms"
        will find relevant sections even if those exact words aren't used.
        """
        if not query or not query.strip():
            return "Please provide a search query."

        top_k = max(1, min(50, top_k))

        response = await search_engine.search(
            query=query.strip(),
            top_k=top_k,
            file_type_filter=file_type if file_type else None,
        )

        if not response.hits:
            stats = indexer.stats
            if stats.total_files == 0:
                return (
                    "No files have been indexed yet. The user needs to configure directories "
                    "for indexing in Settings → Local File Index."
                )
            return f"No results found for: {query}. {stats.total_files} files are indexed."

        lines: list[str] = []
        lines.append(f"Found {response.total_hits} results (search time: {response.search_time_ms:.0f}ms):\n")

        for i, hit in enumerate(response.hits, 1):
            lines.append(f"**[{i}]** `{hit.relative_path}` (score: {hit.score:.3f})")
            lines.append(f"   Path: {hit.file_path}")
            if hit.section:
                lines.append(f"   Section: {hit.section}")
            snippet = hit.snippet.strip()
            if len(snippet) > 300:
                snippet = snippet[:297] + "..."
            lines.append(f"   > {snippet}\n")

        return "\n".join(lines)

    @tool("get_local_file_index_status_tool")
    async def get_local_file_index_status() -> str:
        """Check the status of the local file search index.

        Returns information about indexed files, directories, and indexing progress.
        Use this when the user asks about their indexed files or indexing status.
        """
        stats = indexer.stats

        lines = [
            "## Local File Index Status\n",
            f"- **Status**: {stats.status.value}",
            f"- **Total files**: {stats.total_files}",
            f"- **Total chunks**: {stats.total_chunks}",
            f"- **Directories**: {stats.total_directories}",
            f"- **Errors**: {stats.error_count}",
        ]

        if stats.last_indexed_at:
            lines.append(f"- **Last indexed**: {stats.last_indexed_at.isoformat()}")

        if stats.status == "indexing":
            progress_pct = stats.indexing_progress * 100
            lines.append(f"- **Progress**: {progress_pct:.1f}%")
            if stats.current_file:
                lines.append(f"- **Current file**: {stats.current_file}")

        return "\n".join(lines)

    return [search_local_files, get_local_file_index_status]
