# adapters/

## Overview
LLM adapter layer: LangChain-compatible LiteLLM interface, provider-specific message compatibility shims, message converters, streaming, tool call parsing, schema normalization, and concurrency control.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Module exports | — |
| chat_model/ | Core | LangChain LiteLLM chat-model adapter sub-package. `model.py` — aggregate root (ChatLiteLLM, clean_model_kwargs): config, bind_tools, structured_output, prompt_cache routing. `exceptions.py` — shared adapter exceptions and OpenAI param whitelist constants. `message_mixin.py` — message normalization, developer-role promotion, reasoning_content stamp, ChatResult assembly. `sync_mixin.py` — synchronous generation and streaming with empty-response retry; unified token-usage recording. `async_mixin.py` — asynchronous generation and streaming with concurrency gate and stream stall detection; unified token-usage recording. | ✅ |
| model_capability.py | Core | Model capability detection for reasoning_content echo-back requirements (MiMo, DeepSeek, Kimi/Moonshot) | ✅ |
| concurrency.py | Core | Concurrency gate — per-model and global asyncio semaphores | ✅ |
| converters.py | Core | Bidirectional message format conversion (LangChain ↔ LiteLLM) with explicit message-name preservation; `convert_dict_to_message` preserves `reasoning_content` into `additional_kwargs` (non-streaming parity with stream path) | ✅ |
| metrics.py | Core | Empty response retry metrics tracking | ✅ |
| safety_termination_detector.py | Core | Detects provider safety terminations and suppresses truncated tool_calls to prevent corrupt dispatch | ✅ |
| schema/ | Core | Outbound tool schema normalization sub-package. `normalizer.py` — `normalize_tool_schema` entry point: `$ref`/`$defs` inlining with sibling metadata preserved (overriding description/default survive), top-level composite handling (single object branch extraction, multi-branch `allOf` conjunctive merge / `anyOf`/`oneOf` alternative merge with exclusivity hint folding), nested property-level `anyOf`/`oneOf` unions of multiple object branches merged so no branch's parameters stay hidden, orphan required pruning (Gemini/strict mode), missing-type inference, enum cleanup. `property_merge.py` — property-level branch merging: `merge_allof_branches` (conjunctive: required union, same-name property `const`/`enum` intersection) vs `merge_union_object_branches` (alternative: required dropped except every-branch-common discriminator promotion + excluded from exclusivity hint, same-name const/enum union, keyword-aware exclusivity hint — oneOf "exactly one group", anyOf "at least one"), `apply_union_hint`, per-property `merge_union_property`/`intersect_property`. `anthropic_strip.py` — Anthropic/Claude-specific unsupported JSON Schema keyword stripping with constraint-to-description folding; `is_anthropic_model` gate. | ✅ |
| stream_aggregator.py | Core | Stream data aggregation & XML tag purging — eliminates sync/async stream duplication | ✅ |
| streaming.py | Core | Streaming response parsing, incremental tool call merging | ✅ |
| tool_call_parsers.py | Core | Unified tool call format parsing for multiple LLMs (incl. XML and DeepSeek DSML) | ✅ |
| tool_recovery.py | Core | Cross-provider tool call argument recovery with fallback strategies | ✅ |

## Key Dependencies

- `infra`
- `observability`
- `utils`
