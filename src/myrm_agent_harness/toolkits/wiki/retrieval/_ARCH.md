# retrieval/

## Overview
Wiki search and graph analysis. FTS5+Qdrant hybrid search with CJK bigram support,
multi-dimensional weighted edges, LPA community detection, and graph-based query expansion.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Init | — |
| indexer.py | Core | FTS5+Qdrant hybrid indexer, weighted edge storage, federated graph | ✅ |
| query.py | Core | Query engine with graph traversal expansion | ✅ |
| graph_analysis.py | Core | LPA community detection, knowledge gap discovery, graph insights | ✅ |

## Key Dependencies

- `core` (config, structure)
- `vector` (Qdrant)
- `retriever` (RRF fusion)
