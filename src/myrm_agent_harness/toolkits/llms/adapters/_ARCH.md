# adapters/

## Overview
LLM adapter layer: LangChain-compatible LiteLLM interface, provider-specific message compatibility shims, message converters, streaming, tool call parsing, schema normalization, and concurrency control.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Module exports | — |
| chat_model.py | Core | LangChain LiteLLM adapter aggregate root: config, bind_tools, structured_output, prompt_cache routing | ✅ |
| chat_model_exceptions.py | Core | Shared adapter exceptions and OpenAI param whitelist constants | ✅ |
| chat_model_message_mixin.py | Core | Message normalization, developer-role promotion, reasoning_content stamp, ChatResult assembly | ✅ |
| chat_model_sync_mixin.py | Core | Synchronous generation and streaming with empty-response retry; unified token-usage recording for streaming + non-streaming calls | ✅ |
| chat_model_async_mixin.py | Core | Asynchronous generation and streaming with concurrency gate and stream stall detection; unified token-usage recording | ✅ |
| model_capability.py | Core | Model capability detection for reasoning_content echo-back requirements (MiMo, DeepSeek, Kimi/Moonshot) | ✅ |
| concurrency.py | Core | Concurrency gate — per-model and global asyncio semaphores | ✅ |
| converters.py | Core | Bidirectional message format conversion (LangChain ↔ LiteLLM) with explicit message-name preservation; `convert_dict_to_message` preserves `reasoning_content` into `additional_kwargs` (non-streaming parity with stream path) | ✅ |
| metrics.py | Core | Empty response retry metrics tracking | ✅ |
| safety_termination_detector.py | Core | Detects provider safety terminations and suppresses truncated tool_calls to prevent corrupt dispatch | ✅ |
| schema_normalizer.py | Core | Tool schema normalizer for OpenAI-compatible providers; top-level composite handling (single object branch extraction, multi-branch `allOf` conjunctive merge with same-name property intersection / `anyOf`/`oneOf` alternative merge with exclusivity hint folding), nested property-level `anyOf`/`oneOf` unions of multiple object branches merged the same way so no branch's parameters stay hidden (redefined properties keep the union of `const`/`enum` values, `const` promoted to `enum`), orphan required pruning (Gemini/strict mode), Anthropic-specific unsupported keyword stripping with constraint-to-description folding | ✅ |
| stream_aggregator.py | Core | Stream data aggregation & XML tag purging — eliminates sync/async stream duplication | ✅ |
| streaming.py | Core | Streaming response parsing, incremental tool call merging | ✅ |
| tool_call_parsers.py | Core | Unified tool call format parsing for multiple LLMs (incl. XML and DeepSeek DSML) | ✅ |
| tool_recovery.py | Core | Cross-provider tool call argument recovery with fallback strategies | ✅ |

## Key Dependencies

- `infra`
- `observability`
- `utils`
