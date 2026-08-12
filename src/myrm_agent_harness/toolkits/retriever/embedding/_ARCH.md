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
    | window_policy.py | Core | EmbedWindowPolicy SSOT: model max input tokens, effective chunk budget, EmbedInputTooLargeError, token_counter_for_model（wordpiece 家族 bge/bce/nomic/minilm/e5/gte/paraphrase/jina→estimate、BPE→o200k 统一计数出口） | ✅ |
| factory.py | Core | Embedding factory. CloudEmbedding only (api_key required). Process-wide singleton | ✅ |

## Tests

| File | Coverage |
|------|----------|
| `tests/toolkits/retriever/test_embed_window_policy.py` | window_policy/embed_budget 100%、vector_chunks 100% |
| `tests/integration/test_embed_window_real_embedding_integration.py` | 真实 HTTP 全链路 10 例（wordpiece 字符预算 / BPE token 预算 / 小窗口 0.5 margin / 韩文不超窗 / 中英韩混合 / 超窗 fail-loud / memory 截断 / wiki ingest，关键路径零 mock，本地 OpenAI 兼容端点打通产品自托管 api_base 用法） |
