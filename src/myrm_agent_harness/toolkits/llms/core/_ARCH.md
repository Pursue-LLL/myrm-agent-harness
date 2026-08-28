# core/

## Overview
LLM core: LLM classes, manager, and credential pool.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | LLM core: LLM classes, manager, and credential pool. | — |
| credential_pool.py | Core | Framework-level credential scheduling and rotation. Selectable strategies (round_robin/fill_first/random/least_used) with exponential backoff + jitter, Retry-After support, success acknowledgment, and observability stats. | ✅ |
| key_pool_llm.py | Core | Framework-level LLM wrapper. Transparent key rotation on RATE_LIMIT/AUTH/BILLING errors with Retry-After extraction, success reporting, and tool-binding rotation preservation. Sits below ManagedLLM in the call chain. | ✅ |
| llm.py | Core | LLM core. LiteLLM wrapper providing a unified multi-model invocation interface. Integrates reasoning_timeout floor, thinking headroom adjustment, local endpoint stall-detection relaxation, OpenRouter reasoning_effort rewrite, and native web_search auto-detection. | ✅ |
| manager.py | Core | LLM manager. Provides efficient strategy-aware LLM instance management with LRU caching for improved performance. `get_llm_from_config` 统一 temperature 语义：顶层 `config.temperature` 优先覆盖 `model_kwargs.temperature`，与 agent builder 装配路径保持一致。 | ✅ |
| openrouter_verbosity.py | Core | OpenRouter reasoning_effort → reasoning.effort parameter mapping. Rewrites top-level reasoning_effort into OpenRouter's extra_body.reasoning.effort format, fixing silent parameter discard for models like Claude 4.6+ where LiteLLM's drop_params silently strips reasoning_effort. | ✅ |
| reasoning_timeout.py | Core | Reasoning model timeout floor detection. Provides model-specific minimum timeout values (e.g. o3=600s) for reasoning models with extended thinking phases, preventing premature request_timeout cuts. | ✅ |
| thinking_headroom.py | Core | Thinking model max_tokens headroom adjustment. Proactively raises max_tokens to a safe floor for thinking-capable models (Claude, DeepSeek R1, OpenAI o-series, Gemini 2.5+): effort-based floor when reasoning_effort is set, conservative default floor otherwise (all thinking models default to thinking-on). Prevents truncation caused by thinking tokens consuming the output budget. | ✅ |

Wire protocol selection is configured via `LLMConfig.wire_protocol` / `ChatLiteLLM.wire_protocol` and implemented in `adapters/wire/` (see [adapters/wire/_ARCH.md](../adapters/wire/_ARCH.md)).

## Key Dependencies

- `utils`
