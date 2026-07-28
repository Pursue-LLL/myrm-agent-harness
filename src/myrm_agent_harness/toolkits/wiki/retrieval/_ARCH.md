# retrieval/

## Overview
Wiki search and graph analysis. FTS5+Qdrant hybrid search with CJK bigram support,
multi-dimensional weighted edges, LPA community detection, graph-based query expansion,
and sidecar-first hierarchical retrieval (L0/L1 route + L2 article grounding).

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Init | — |
| indexer.py | Core | FTS5+Qdrant hybrid indexer for L2 concepts, weighted edge storage, federated search | ✅ |
| sidecar_index.py | Core | SidecarIndexMixin: L0/L1 directory sidecar FTS5+Qdrant indexing, search, and lifecycle (inherited by WikiIndexer) | ✅ |
| tokenizer.py | Core | FTS5 query tokenizer with CJK bigram support and stop word filtering | ✅ |
| graph_store.py | Core | Knowledge graph BFS traversal, federated graph queries, insight delegation | ✅ |
| graph_analysis.py | Core | LPA community detection, knowledge gap discovery, graph insights | ✅ |
| query.py | Core | Query engine with graph traversal expansion and context budgeted L0/L1→L2 loading; prepends `hot.md` context inside wiki_query only (no global middleware); emits layered source snippets for sidecar + article evidence | ✅ |

## Key Dependencies

- `core` (config, structure)
- `vector` (Qdrant)
- `retriever` (RRF fusion)
