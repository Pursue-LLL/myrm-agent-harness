"""Local file search toolkit.

Provides semantic search over user's local files with explicit authorization,
SHA256 incremental indexing, and hybrid retrieval (vector + optional reranking).

[INPUT]
- .config::LocalFileSearchConfig (POS: configuration model)
- .indexer::LocalFileIndexer (POS: indexing engine)
- .search::LocalFileSearchEngine (POS: search engine)
- .local_file_search_agent_tools::create_local_file_search_tools (POS: LangChain tool factory)

[OUTPUT]
- LocalFileSearchConfig: Configuration model
- LocalFileIndexer: Indexing engine
- LocalFileSearchEngine: Search engine
- create_local_file_search_tools: Tool factory for Agent integration

[POS]
Local file search toolkit entry point. Aggregates indexer, search engine, and tool factory.
Designed for explicit user authorization (deny-by-default), not background scanning.
"""

from myrm_agent_harness.toolkits.local_file_search.config import (
    SUPPORTED_EXTENSIONS,
    VECTOR_COLLECTION_NAME,
    LocalFileSearchConfig,
)
from myrm_agent_harness.toolkits.local_file_search.indexer import LocalFileIndexer
from myrm_agent_harness.toolkits.local_file_search.local_file_search_agent_tools import (
    create_local_file_search_tools,
)
from myrm_agent_harness.toolkits.local_file_search.models import (
    FileRecord,
    IndexedDirectory,
    IndexStats,
    IndexStatus,
    SearchHit,
    SearchResponse,
)
from myrm_agent_harness.toolkits.local_file_search.search import LocalFileSearchEngine

__all__ = [
    "SUPPORTED_EXTENSIONS",
    "VECTOR_COLLECTION_NAME",
    "FileRecord",
    "IndexStats",
    "IndexStatus",
    "IndexedDirectory",
    "LocalFileIndexer",
    "LocalFileSearchConfig",
    "LocalFileSearchEngine",
    "SearchHit",
    "SearchResponse",
    "create_local_file_search_tools",
]
