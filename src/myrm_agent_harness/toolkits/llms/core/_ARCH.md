# core/

## Overview
LLM core: LLM classes, manager, and credential pool.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | LLM core: LLM classes, manager, and credential pool. | — |
| credential_pool.py | Core | Framework-level credential scheduling and rotation. Selectable strategies (round_robin/fill_first/random/least_used) with exponential backoff + jitter, Retry-After support, success acknowledgment, and observability stats. | ✅ |
| key_pool_llm.py | Core | Framework-level LLM wrapper. Transparent key rotation on RATE_LIMIT/AUTH/BILLING errors with Retry-After extraction, success reporting, and tool-binding rotation preservation. Sits below ManagedLLM in the call chain. | ✅ |
| llm.py | Core | LLM core. LiteLLM wrapper providing a unified multi-model invocation interface. Integrates reasoning_timeout floor and native web_search auto-detection. | ✅ |
| manager.py | Core | LLM manager. Provides efficient strategy-aware LLM instance management with LRU caching for improved performance | ✅ |
| reasoning_timeout.py | Core | Reasoning model timeout floor detection. Provides model-specific minimum timeout values (e.g. o3=600s) for reasoning models with extended thinking phases, preventing premature request_timeout cuts. | ✅ |

## Key Dependencies

- `utils`
