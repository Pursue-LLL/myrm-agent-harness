# retriever/

## Overview
retrievalhandlestool

Detailed design: [RETRIEVER_SYSTEM.md](RETRIEVER_SYSTEM.md)

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | retrievalhandlestool | — |
| bm25_retrieval.py | Core | BM25 sparse retrieval engine. Builds an in-memory inverted index from document chunks and | ✅ |
| engine.py | Core | Retrieval tools wrapper. Provides hybrid retrieval and reranking, integrating BM25, vector search, | ✅ |
| fusion_strategies.py | Core | Score-fusion utilities for hybrid retrieval. Merges multiple ranked lists into a single | ✅ |
| hybrid_retriever.py | Core | Stable public facade for hybrid retrieval. Re-exports the coordinator so callers need not | ✅ |
| performance_monitor.py | Core | Provides PerformanceMonitor, get_performance_monitor. | ✅ |
| qdrant_retrieval.py | Core | Qdrant persistent vector retriever. Wraps vector store search capability, providing automatic text-t | ✅ |

| Submodule | Description |
|-----------|-------------|
| bm25/ | BM25 retrieval module. |
| embedding/ | Embedding Service Toolkit. |
| hybrid_search/ | Hybrid retrieval module. |
| preprocessing/ | documentpre-handlesmodule |
| reranker/ | Reranker Service Toolkit. |
| splitter/ | textsplittoolmodule |
| vector_search/ | Pure in-memory vector retrieval module |

## Key Dependencies

- `utils`
