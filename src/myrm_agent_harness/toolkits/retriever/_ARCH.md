# retriever/

## Overview

Hybrid RAG retrieval toolkit: preprocessing → split → embed → parallel vector + BM25 → fusion → rerank. Framework-agnostic; no business-layer imports.

Detailed design: [RETRIEVER_SYSTEM.md](RETRIEVER_SYSTEM.md)

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Public exports for hybrid retrieval entrypoints | ✅ |
| `autocut.py` | Core | Score-discontinuity autocut for dynamic truncation after rerank | ✅ |
| `bm25_retrieval.py` | Core | BM25 sparse retrieval; in-memory inverted index over document chunks | ✅ |
| `cjk_tokenizer.py` | Core | Single-pass position-preserving CJK unigram/bigram & ASCII word tokenizer, expansion budget protection, and CjkFtsQueryPlanner for two-tier FTS5 query synthesis | ✅ |
| `engine.py` | Core | Retrieval tools wrapper: hybrid retrieval, multi-query BM25 reranking & reranking orchestration | ✅ |
| `fusion_strategies.py` | Core | Score fusion utilities (deterministic RRF with tie-breaking, weighted RRF & recall debug) for hybrid lists | ✅ |
| `hybrid_retriever.py` | Core | Stable public facade re-exporting the hybrid coordinator | ✅ |
| `performance_monitor.py` | Core | `PerformanceMonitor` and `get_performance_monitor` hooks | ✅ |
| `qdrant_retrieval.py` | Core | Qdrant-backed vector retriever with automatic text handling | ✅ |

| Submodule | Description |
|-----------|-------------|
| `bm25/` | BM25 algorithm and tokenization |
| `embedding/` | Local/cloud embedding services |
| `hybrid_search/` | Hybrid search pipeline coordinator |
| `preprocessing/` | Document filtering, cleanup, normalization |
| `reranker/` | Post-retrieval reranking |
| `splitter/` | Document chunking strategies |
| `sufficiency/` | RSG post-retrieval sufficiency guard — [sufficiency/_ARCH.md](sufficiency/_ARCH.md) |
| `vector_search/` | In-memory / backend vector search helpers |
| `ingest/` | Dual-Lane Ingest Pipeline with bounded backpressure — [ingest/_ARCH.md](ingest/_ARCH.md) |

## Key Dependencies

- `utils`
- Optional `[retrieval]`: langchain-text-splitters, numpy, jieba, rank-bm25, tenacity
