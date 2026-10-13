# retrieval/

## Overview
Wiki search and graph analysis. FTS5+Qdrant hybrid search with CJK bigram support,
multi-dimensional weighted edges, LPA community detection, graph-based query expansion,
and sidecar-first hierarchical retrieval (L0/L1 route + L2 article grounding).

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Wiki 检索域入口包：导出 `WikiIndexer` 与 `WikiQueryEngine` | ✅ |
| indexer.py | Core | Wiki indexer lifecycle: FTS5 schema bootstrap + one-time concept-identity migration, page-key canonicalization (`_index_key`), weighted edge storage whose targets are resolved to page keys at write time (markdown links, Wikilinks, Metric source_systems) with forward-reference relinking, `graph_store` property, and `get_concept_links` delegation | ✅ |
| fts_search.py | Core | FtsSearchMixin: FTS5 truth upsert/search/get_truth with `search_terms` CJK index column (one row per page under its on-disk key; delete accepts any spelling), real-time edge extraction on upsert, raw-text interim indexing, publish_status gate, vector upsert/delete/search and RRF fusion | ✅ |
| edge_links.py | Core | Edge-target canonicalization (`canonical_edge_target`, markdown links relative to the linking page) and `relink_dangling_edges` for links written before their target page existed | ✅ |
| identity_migration.py | Core | One-time `PRAGMA user_version` migration merging legacy index rows keyed by compile names into on-disk page keys; rows without a backing page are left untouched | ✅ |
| sidecar_index.py | Core | SidecarIndexMixin: L0/L1 directory sidecar FTS5+Qdrant indexing, search, and lifecycle (inherited by WikiIndexer) | ✅ |
| tokenizer.py | Core | FTS5 query tokenizer with CJK bigram support; `extract_query_terms()` shared with index routing | ✅ |
| graph_store.py | Core | Knowledge graph BFS traversal, alias asset lookup, bidirectional concept link aggregation (lookup key canonicalized like writes) with Unicode CJK safe snippet/line-number and clean markdown-stripped heading extraction, insight delegation | ✅ |
| graph_tables.py | Core | Federated node/edge SQL over the local and attached public indexes; `raw:` interim and sidecar rows are not graph nodes. Shared by the viewer graph and the insights | ✅ |
| graph_analysis.py | Core | LPA community detection and graph insights over the viewer's node/edge set: mutual links count once, cohesion ≤ 1, clusters need ≥ 2 pages, isolated and bridge gaps capped separately, members listed hub-first | ✅ |
| best_first.py | Core | Best-first priority-queue convergence + raw_claim frontmatter rerank + claim-health multipliers (supported/contested/stale) | ✅ |
| query.py | Core | Query engine: hot + recent log prefix, index-first seeds → sidecar scope → FTS rerank → best-first graph converge; derived `confidence_score`; fail-closed `refused` verdict (`_refused_verdict` — out-of-bounds `min_answer_confidence` refuses); `retrieval_trace` metadata; SourceSnippet incl. claims + raw evidence excerpt + `claim_text` + `claim_confidence` + snapshot_status + evidence SHA + asset hits | ✅ |
| source_citations.py | Core | Shared LLM-Wiki citation SSOT; `snippet` (raw excerpt) + `claim_text` + `resource_uri` + `superseded_from_uri` for claim snippets with `evidence_path`; `format_evidence_cards_context` for line-level Evidence Card anchor injection and answer contract | ✅ |
| asset_index.py | Core | Wiki asset caption indexer: FTS5 + Qdrant `wiki_assets`, SHA256 skip, provenance scan, orphan purge | ✅ |
| vector_chunks.py | Core | Embed-window-aware multi-chunk vector upsert/delete + search hit collapse (shared by indexer/sidecar/asset) | ✅ |
| reindex_vectors.py | Core | Rebuild published concept, sidecar, and optional asset vectors after embedding model or chunk policy changes | ✅ |


## Key Dependencies

- `core` (config, structure, link_resolver)
- `vector` (Qdrant)
- `retriever` (RRF fusion)
