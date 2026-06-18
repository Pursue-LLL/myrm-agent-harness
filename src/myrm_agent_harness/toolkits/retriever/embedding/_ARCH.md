# embedding/

## Overview
Embedding Service Toolkit.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Embedding Service Toolkit. | — |
| base.py | Core | Embedding contract layer. Declares the abstract interface that every embedding backend | ✅ |
| cache.py | Core | Embedding cache layer. Provides a two-tier caching mechanism (memory + SQLite) that sits | ✅ |
| cloud_embedding.py | Core | Cloud embedding backend. Translates EmbeddingService into LiteLLM API calls with auto batch splitting (count + chars dual protection), retry, and dimension detection | ✅ |
| local_embedding.py | Core | Local embedding backend. Offline-capable ONNX embeddings via fastembed (optional dep) | ✅ |
| factory.py | Core | Embedding factory. Intelligent fallback: cloud → local → error. Process-wide singleton | ✅ |
