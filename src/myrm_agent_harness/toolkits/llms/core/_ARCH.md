# core/

## Overview
LLM core: LLM classes, manager, and credential pool.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | LLM core: LLM classes, manager, and credential pool. | — |
| credential_pool.py | Core | Framework-level credential scheduling and rotation. Selectable strategies (round_robin/fill_first/random/least_used) with exponential backoff + jitter, Retry-After support, success acknowledgment, and observability stats. | ✅ |
| deepseek_reasoning.py | Core | DeepSeek reasoning_effort & thinking protocol parameter mapping. Maps reasoning effort levels ('low', 'high', 'max') and handles thinking on/off ('enabled'/'disabled') for DeepSeek models to guarantee compatibility and tool-call reasoning_content safety. | ✅ |
| key_pool_llm.py | Core | Framework-level LLM wrapper. Transparent key rotation on RATE_LIMIT/AUTH/BILLING errors with Retry-After extraction, success reporting, and challenge circuit breaker (immediately halts pool rotation and raises EgressChallengeBlockedError on WAF/anti-bot blocks). Sits below ManagedLLM in the call chain. | ✅ |
| llm.py | Core | LLM core. LiteLLM wrapper providing a unified multi-model invocation interface. Integrates reasoning_timeout floor, thinking headroom adjustment, local endpoint stall-detection relaxation, OpenRouter reasoning_effort rewrite, and native web_search auto-detection. Extra model kwargs are also forwarded to OpenAI-compatible providers as `extra_body` entries (a caller `extra_body` wins and is copied, never mutated); the output cap, `extra_body` itself and the factory-only `supports_reasoning` switch are never forwarded that way, because the SDK lets `extra_body` override typed fields and would put the pre-headroom cap on the wire. First-party Anthropic Messages calls skip the `extra_body` copies entirely (that API rejects the field; LiteLLM maps `reasoning_effort` to `thinking` itself). | ✅ |
| manager.py | Core | LLM manager. Provides efficient strategy-aware LLM instance management with LRU caching for improved performance. `get_llm_from_config` 统一 temperature 与 reasoning_effort 语义：顶层字段优先覆盖 `model_kwargs`，与 agent builder 装配路径保持一致。 | ✅ |
| openai_reasoning.py | Core | OpenAI reasoning_effort parameter remap & normalization. Remaps non-standard reasoning effort levels ('minimal'→'low', 'xhigh'/'max'→'high') for OpenAI reasoning models (o1, o3, o4, GPT-5.6), strips unsupported 'off' values, and safely removes reasoning_effort for non-reasoning models (gpt-4o, gpt-4o-mini) to prevent API HTTP 400 Bad Request errors. | ✅ |
| openrouter_verbosity.py | Core | OpenRouter reasoning_effort → reasoning.effort parameter mapping. Rewrites top-level reasoning_effort into OpenRouter's extra_body.reasoning.effort format, fixing silent parameter discard for models like Claude 4.6+ where LiteLLM's drop_params silently strips reasoning_effort. | ✅ |
| reasoning_profile.py | Core | Reasoning model single source of truth (SSOT) profile and intent contract. Unifies timeout floors, output token headroom budgets, and three-tier intent resolution (L1 explicit intent, L2 config toggle, L3 authoritative catalog fallback). `apply_thinking_headroom` raises a configured cap below the floor within the model's documented output ceiling; the raised value is what reaches the provider. | ✅ |
| reasoning_timeout.py | Core | Reasoning model timeout floor detection facade. Delegates to reasoning_profile SSOT for unified timeout floors. | ✅ |
| thinking_headroom.py | Core | Thinking model max_tokens headroom adjustment facade. Delegates to reasoning_profile SSOT for token budget floors. | ✅ |

Wire protocol selection is configured via `LLMConfig.wire_protocol` / `ChatLiteLLM.wire_protocol` and implemented in `adapters/wire/` (see [adapters/wire/_ARCH.md](../adapters/wire/_ARCH.md)).

## Key Dependencies

- `utils`
