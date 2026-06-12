# retriever/

## Overview
retrievalhandlestool

Detailed design: [RETRIEVER_SYSTEM.md](RETRIEVER_SYSTEM.md)

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | retrievalhandlestool | — |
| autocut.py | Core | Score-discontinuity autocut. Detects largest gap in rerank scores for dynamic truncation. | ✅ |
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
| sufficiency/ | Retrieval Sufficiency Guard (RSG) — LLM-based evaluation of retrieval completeness with negative constraint detection. Conditionally activated post-retrieval to assess result quality and guide re-search. |
| vector_search/ | Pure in-memory vector retrieval module |

## Key Dependencies

- `utils`
