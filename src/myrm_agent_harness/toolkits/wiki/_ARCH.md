# wiki/

## Overview
LLM-Wiki toolkit: Karpathy-architecture knowledge base engine. Compiles raw documents into
structured, cross-linked wiki articles with SHA256 incremental caching, FTS5+Qdrant hybrid
search, 3D knowledge graph with LPA community detection, knowledge drift defense, and
LLM-driven wikilink enrichment.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Wiki toolkit entry point | ✅ |
| wiki_agent_tools.py | Core | LangChain tool integration layer (auto-compile on ingest, knowledge compounding on query, HTML→Markdown URL fetching) | ✅ |

| Submodule | Description |
|-----------|-------------|
| core/ | Config (purpose, compile strategy), types, file structure (incl. scan_folder with auto-ignore for .git/node_modules/etc) |
| maintenance/ | Linter: health checks, drift/stale detection, LLM link enrichment |
| pipeline/ | Compiler (SHA256 cache, auto-retry queue), pending edits (HITL) |
| retrieval/ | Indexer (FTS5+CJK, edges with weight, LPA, graph insights), query engine (graph expansion) |

## Key Dependencies

- `utils` (logger, context_format)
- `web_fetch` (MarkdownGenerator for URL→Markdown conversion)
- `web_search` (deep research integration)
- `memory` (auto-archive from conversations)
- `vector` (Qdrant hybrid search)
- `retriever` (RRF fusion)
