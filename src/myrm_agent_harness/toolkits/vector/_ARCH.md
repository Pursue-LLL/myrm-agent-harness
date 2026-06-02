# vector/

## Overview
Vector Store Toolkit — unified async vector storage and retrieval.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Vector Store Toolkit — unified async vector storage and retrieval. | — |
| base.py | Core | Vector store abstraction layer. Defines backend-agnostic vector store interface and data models, | ✅ |
| config.py | Config | Generic vector store configuration. Defines deployment modes and connection parameters, backend-agno | ✅ |
| pool.py | Core | Vector store connection pool. Manages a pool of VectorStore instances for high-concurrency | ✅ |
| warmer.py | Core | Vector store cache warm-up toolkit. Provides a generic warm-up mechanism for any | ✅ |

| Submodule | Description |
|-----------|-------------|
| qdrant/ | Qdrant Vector Store — built-in implementation. |
