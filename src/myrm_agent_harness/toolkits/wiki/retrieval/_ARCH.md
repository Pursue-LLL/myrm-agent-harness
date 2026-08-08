# retrieval/

## Overview
Wiki search and graph analysis. FTS5+Qdrant hybrid search with CJK bigram support,
multi-dimensional weighted edges, LPA community detection, graph-based query expansion,
and sidecar-first hierarchical retrieval (L0/L1 route + L2 article grounding).

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Init | — |
| indexer.py | Core | FTS5+Qdrant hybrid indexer for L2 concepts; `wiki_index_meta` publish_status gate; weighted edge storage + `get_outgoing_edges`; federated search | ✅ |
| sidecar_index.py | Core | SidecarIndexMixin: L0/L1 directory sidecar FTS5+Qdrant indexing, search, and lifecycle (inherited by WikiIndexer) | ✅ |
| tokenizer.py | Core | FTS5 query tokenizer with CJK bigram support; `extract_query_terms()` shared with index routing | ✅ |
| graph_store.py | Core | Knowledge graph BFS traversal, federated graph queries, insight delegation | ✅ |
| graph_analysis.py | Core | LPA community detection, knowledge gap discovery, graph insights | ✅ |
| best_first.py | Core | Best-first priority-queue convergence + raw_claim frontmatter rerank + claim-health multipliers (supported/contested/stale) | ✅ |
| query.py | Core | Query engine: hot + recent log prefix, index-first seeds → sidecar scope → FTS rerank → best-first graph converge; derived `confidence_score`; `retrieval_trace` metadata; SourceSnippet incl. claims + raw evidence excerpt + `claim_text` + `claim_confidence` + snapshot_status + evidence SHA + asset hits | ✅ |
| source_citations.py | Core | Shared LLM-Wiki citation SSOT; `snippet` (raw excerpt) + `claim_text` + `resource_uri` + `superseded_from_uri` for claim snippets with `evidence_path`; optional `structure` for live digest when pin missing | ✅ |
| asset_index.py | Core | Wiki asset caption indexer: FTS5 + Qdrant `wiki_assets`, SHA256 skip, provenance scan, orphan purge | ✅ |
| vector_chunks.py | Core | Embed-window-aware multi-chunk vector upsert/delete + search hit collapse (shared by indexer/sidecar/asset) | ✅ |
| reindex_vectors.py | Core | Rebuild published concept vectors after embedding model or chunk policy changes | ✅ |

## Key Dependencies

- `core` (config, structure)
- `vector` (Qdrant)
- `retriever` (RRF fusion)
