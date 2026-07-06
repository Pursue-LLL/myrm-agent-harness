# retrieval/

## Overview
Wiki search and graph analysis. FTS5+Qdrant hybrid search with CJK bigram support,
multi-dimensional weighted edges, LPA community detection, and graph-based query expansion.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Init | — |
| indexer.py | Core | FTS5+Qdrant hybrid indexer, weighted edge storage, federated search | ✅ |
| tokenizer.py | Core | FTS5 query tokenizer with CJK bigram support and stop word filtering | ✅ |
| graph_store.py | Core | Knowledge graph BFS traversal, federated graph queries, insight delegation | ✅ |
| graph_analysis.py | Core | LPA community detection, knowledge gap discovery, graph insights | ✅ |
| query.py | Core | Query engine with graph traversal expansion | ✅ |

## Key Dependencies

- `core` (config, structure)
- `vector` (Qdrant)
- `retriever` (RRF fusion)
