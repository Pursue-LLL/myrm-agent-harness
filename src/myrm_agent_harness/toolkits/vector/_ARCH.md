# vector/

## Overview
Vector Store Toolkit — unified async vector storage and retrieval.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Vector Store Toolkit — unified async vector storage and retrieval. | — |
| base.py | Core | Vector store abstraction layer. Defines backend-agnostic vector store interface and data models, including `is_persistent` (default `True`) — backends backed by ephemeral in-memory storage (e.g. Qdrant `:memory:` fallback) override it to `False` so callers can surface degraded non-durable mode | ✅ |
| config.py | Config | Generic vector store configuration. Defines deployment modes and connection parameters, backend-agno | ✅ |
| pool.py | Core | Vector store connection pool. Manages a pool of VectorStore instances for high-concurrency | ✅ |
| quantization.py | Core | Int8 vector quantization with per-row dynamic scale & zero-copy dot product similarity (4x memory reduction) | ✅ |
| warmer.py | Core | Vector store cache warm-up toolkit. Provides a generic warm-up mechanism for any | ✅ |

| Submodule | Description |
|-----------|-------------|
| qdrant/ | Qdrant Vector Store — built-in implementation. |
