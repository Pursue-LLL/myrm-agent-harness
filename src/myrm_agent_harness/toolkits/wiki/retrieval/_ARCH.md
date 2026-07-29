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
| best_first.py | Core | Best-first priority-queue convergence + raw_claim frontmatter rerank | ✅ |
| query.py | Core | Query engine: index-first seeds → sidecar scope → FTS rerank → best-first graph converge; SourceSnippet incl. claims + snapshot_status | ✅ |

## Key Dependencies

- `core` (config, structure)
- `vector` (Qdrant)
- `retriever` (RRF fusion)
