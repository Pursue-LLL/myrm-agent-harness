# wiki/

## Overview
LLM-Wiki toolkit: Karpathy-architecture knowledge base engine. Compiles raw documents into
structured, cross-linked wiki articles with SHA256 incremental caching, FTS5+Qdrant hybrid
search, 3D knowledge graph with LPA community detection, knowledge drift defense, L0/L1
directory sidecars, bottom-up incremental DAG refresh, and LLM-driven wikilink enrichment.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Wiki toolkit entry point | ✅ |
| wiki_agent_tools.py | Core | LangChain tool integration: **ingest/query/apply** agent tools; admin compile/maintain via REST. Auto-compile on ingest, knowledge compounding on query, FetchEngine URL/binary ingest. Query metadata emits layered citations + claim snapshot_status + resource_uri + superseded_from_uri via shared `build_wiki_query_sources(structure=...)`. | ✅ |

| Submodule | Description |
|-----------|-------------|
| core/ | Config (purpose, compile strategy), types (ConceptInfo, WikiArticle, CompileResult, SourceSnippet, QueryResult, LintIssue/Result, WikiMetadata), file structure (incl. scan_folder with auto-ignore for .git/node_modules/etc), parsers (LLM response → ConceptInfo) |
| maintenance/ | Linter: health checks, drift/stale detection, knowledge-gap analysis, LLM link enrichment (no LLM auto-write for incomplete articles) |
| diagnostics/ | Deterministic structural lint SSOT + offline retrieval benchmark (CI gate) |
| pipeline/ | Compiler (parallel batch ingestion, SHA256 cache, auto-retry queue, **survey/** structure scan + facet seed carry-forward, compile phase SSE), **contradiction_synthesis/** (CCSP Step 2.5 evolution pages), sidecar builder (L0/L1 bottom-up DAG), cognitive_map (OKF index/log/hot writers), postprocess (backlink generation, metadata persistence), **apply/** (narrow-write SSOT), **raw_gate/** (raw publication gate SSOT), publication gate (WPG SSOT + stale guard + move reindex), pending edits (HITL stage/approve) |
| portability/ | Full vault ZIP export + local git auto-commit (`vault_archive`, `vault_git`) |
| retrieval/ | Indexer (FTS5 hybrid search, vector upsert/delete, sidecar tiered indexing, weighted graph edges), tokenizer (CJK bigram FTS5 query builder), best_first (priority-queue convergence + raw_claim rerank), graph_store (BFS traversal, federated graph queries, insights), query engine (hot + recent log prefix, index/sidecar/FTS seeds → best-first converge, citation snippet extraction, asset hit fusion), asset_index (wiki/assets caption FTS5 + Qdrant + orphan purge) |

## Key Dependencies

- `web_fetch` (FetchEngine for URL ingestion with YouTube/Bilibili subtitle extraction + multi-tier fallback; MarkdownGenerator as fallback converter)
- `core.security.http.secure_fetch` (secure_get fallback for URL ingestion when FetchEngine unavailable)
- `utils` (logger, context_format)
- `web_search` (deep research integration)
- `memory` (auto-archive from conversations)
- `vector` (Qdrant hybrid search)
- `retriever` (RRF fusion)
