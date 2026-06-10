# code_index/

## Overview
Workspace code indexer toolkit. Provides on-demand FTS5 + optional Vector hybrid search
over source code files for semantic code search.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Public exports (CodeIndexer, CodeIndexConfig) | — |
| config.py | Core | Indexing configuration (file filters, limits, search params) | ✅ |
| indexer.py | Core | FTS5+Vector hybrid code indexer with mtime-based incremental updates | ✅ |
| symbol_extractor.py | Core | Regex-based symbol extraction for 15+ languages | ✅ |

## Key Dependencies

- `myrm_agent_harness.toolkits.retriever.fusion_strategies` (rrf_fusion)
- `myrm_agent_harness.toolkits.vector.base` (VectorDocument)
- `myrm_agent_harness.toolkits.memory.protocols.embedding` (EmbeddingProtocol, optional)
- `myrm_agent_harness.toolkits.memory.protocols.vector` (VectorStoreProtocol, optional)
- `myrm_agent_harness.utils.db.sqlite` (hardening, optional)

## Design Decisions

1. **No background daemon**: Indexes on-demand via `ensure_indexed()`, triggered by code_search_tool or @codebase mention.
2. **Incremental via mtime**: Only re-indexes files whose mtime_ns changed since last index.
3. **Regex over AST**: Uses regex-based symbol extraction (15+ languages) instead of tree-sitter to avoid native dependencies. Trades ~5% accuracy for zero setup cost.
4. **FTS5 + Vector hybrid**: Same architecture as WikiIndexer (proven in production), with code-specific tokenization.
5. **Graceful degradation**: Works without vector store (FTS5-only mode) for SaaS or environments without embedding models.
