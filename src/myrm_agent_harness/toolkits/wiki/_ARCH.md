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
| wiki_agent_tools.py | Core | LangChain tool integration layer (auto-compile on ingest, knowledge compounding on query, URL fetching via FetchEngine with YouTube/Bilibili subtitle extraction and secure_get fallback). Supports binary document ingestion (PDF/DOCX/XLSX/PPTX) via file_parsers, auto-chunking for large documents, and FTS5 raw indexing for immediate searchability. | ✅ |

| Submodule | Description |
|-----------|-------------|
| core/ | Config (purpose, compile strategy), types (ConceptInfo, WikiArticle, CompileResult, SourceSnippet, QueryResult, LintIssue/Result, WikiMetadata), file structure (incl. scan_folder with auto-ignore for .git/node_modules/etc), parsers (LLM response → ConceptInfo) |
| maintenance/ | Linter: health checks, drift/stale detection, knowledge-gap analysis, LLM link enrichment |
| pipeline/ | Compiler (parallel batch ingestion, SHA256 cache, auto-retry queue, raw text FTS5 pre-indexing on enqueue), postprocess (index building, backlink generation, metadata persistence), pending edits (HITL) |
| retrieval/ | Indexer (FTS5 hybrid search, vector upsert/delete), tokenizer (CJK bigram FTS5 query builder), graph_store (BFS traversal, federated graph queries, insights), query engine (graph expansion, citation snippet extraction) |

## Key Dependencies

- `web_fetch` (FetchEngine for URL ingestion with YouTube/Bilibili subtitle extraction + multi-tier fallback; MarkdownGenerator as fallback converter)
- `core.security.http.secure_fetch` (secure_get fallback for URL ingestion when FetchEngine unavailable)
- `utils` (logger, context_format)
- `web_search` (deep research integration)
- `memory` (auto-archive from conversations)
- `vector` (Qdrant hybrid search)
- `retriever` (RRF fusion)
