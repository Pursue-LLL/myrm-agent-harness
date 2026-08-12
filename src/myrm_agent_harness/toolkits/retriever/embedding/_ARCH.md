# embedding/

## Overview
Embedding Service Toolkit.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Embedding Service Toolkit. | — |
| base.py | Core | Embedding contract layer. Declares the abstract interface that every embedding backend | ✅ |
| cache.py | Core | Embedding cache layer. Provides a two-tier caching mechanism (memory + SQLite) that sits | ✅ |
| cloud_embedding.py | Core | Cloud embedding backend. Translates EmbeddingService into LiteLLM API calls with auto batch splitting (count + chars dual protection), retry, dimension detection, and embed-window preflight. Supports Ollama via api_base | ✅ |
    | window_policy.py | Core | EmbedWindowPolicy SSOT: model max input tokens, effective chunk budget, EmbedInputTooLargeError, token_counter_for_model（wordpiece→estimate/BPE→o200k 统一计数出口） | ✅ |
| factory.py | Core | Embedding factory. CloudEmbedding only (api_key required). Process-wide singleton | ✅ |
