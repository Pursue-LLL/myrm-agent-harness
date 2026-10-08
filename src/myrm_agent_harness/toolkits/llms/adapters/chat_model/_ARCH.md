# chat_model/

## Overview
LangChain LiteLLM chat-model adapter: aggregate root (`model.py`) plus sync/async generation & streaming mixins and shared exceptions.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Sub-package exports. | — |
| model.py | Core | `ChatLiteLLM`, `clean_model_kwargs`: config, bind_tools, structured_output, prompt-cache routing, and OpenCode gateway session-affinity headers injection. Aggregate root composing the mixins below. | ✅ |
| allowed_params.py | Core | `inject_allowed_params` (bound as `ChatLiteLLM._inject_allowed_params`): white-lists a call's own parameters and the framework-required set against LiteLLM's provider filter via `allowed_openai_params`; calls to the first-party Anthropic Messages API get no whitelist, because that API rejects the raw OpenAI-shaped copies. | ✅ |
| exceptions.py | Core | Shared adapter exceptions (`EmptyChoicesError`/`EmptyStreamError`/`StreamStallTimeoutError`) and OpenAI param whitelist constants (including `service_tier` and `extra_headers` passthrough). | ✅ |
| output_cap_recovery.py | Core | `ChatLiteLLMOutputCapMixin` (bound by `model.py`) owns a request's output-token budget. `_apply_output_budget` applies the one-shot truncation-boost override and then clamps to the model ceiling this endpoint already rejected (lower-only, so a boosted budget still fits). When a provider rejects `max_tokens`, `recover_output_cap` lets the generation loops retry with the limit the error states (`errors.output_limit`) and nothing else changed, so the provider-side prompt-prefix cache still hits. A model ceiling is remembered per (model, base URL) in a bounded, expiring memo; a context-window remainder keeps a 64-token margin and applies to that request only. Refused when the value would not lower the budget, is under 500 tokens, leaves no room for the request's own `thinking.budget_tokens`, or the rejection status is not 400/413/422. Streaming loops retry only while nothing was yielded to the consumer. | ✅ |
| message_mixin.py | Core | `ChatLiteLLMMessageMixin`: message normalization, developer-role promotion, reasoning_content stamp, outbound wire projection sanitization, image_url detail sanitization, ChatResult assembly. Derives `stream_complete` from `finish_reason` and passes it into non-streaming `convert_dict_to_message` and the final tool-call chunk builder, so abnormal endings refuse arg repair. Decodes HTML-escaped tool-call args only for xAI Grok (decided from the configured model id). | ✅ |
| sync_mixin.py | Core | `ChatLiteLLMSyncMixin`: synchronous generation and streaming with empty-response retry and unified token-usage recording; the consumed provider stream is tracked by the aggregator so a connection cut mid tool call is recognised. | ✅ |
| async_mixin.py | Core | `ChatLiteLLMAsyncMixin`: asynchronous generation and streaming with concurrency gate and stream stall detection, unified token-usage recording; the consumed provider stream is tracked by the aggregator so a connection cut mid tool call is recognised. | ✅ |

## Key Dependencies

- `toolkits.llms.adapters` (converters / streaming / concurrency / stream_aggregator / tool_recovery / model_capability / safety_termination_detector)
- `utils.token_economics`
