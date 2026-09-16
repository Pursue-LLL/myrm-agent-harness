# adapters/

## Overview
LLM adapter layer: LangChain-compatible LiteLLM interface, provider-specific message compatibility shims, message converters, streaming, tool call parsing, schema normalization, and concurrency control.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Module exports | — |
| gateway_normalizer.py | Core | OpenAI compatible gateway normalizer: adaptive parameter stripping and compatibility mapping on HTTP 400 format/unsupported errors (stream_options, parallel_tool_calls, reasoning_effort, max_completion_tokens -> max_tokens, temperature, response_format, user); schema-shape rejections strip only the internal tool_calls_transport with per-endpoint memory | ✅ |
| chat_model/ | Core | LangChain LiteLLM chat-model adapter sub-package. `model.py` — aggregate root (ChatLiteLLM, clean_model_kwargs): config, bind_tools, structured_output, prompt_cache routing. `exceptions.py` — shared adapter exceptions and OpenAI param whitelist constants. `message_mixin.py` — message normalization, developer-role promotion, reasoning_content stamp, ChatResult assembly. `sync_mixin.py` — synchronous generation and streaming with empty-response retry; unified token-usage recording; gateway 400 auto-downgrade retry. `async_mixin.py` — asynchronous generation and streaming with concurrency gate and stream stall detection; unified token-usage recording; gateway 400 auto-downgrade retry. | ✅ |
| model_capability.py | Core | Model capability detection for reasoning_content echo-back requirements (MiMo, DeepSeek, Kimi/Moonshot) and local weak endpoint detection for grammar/schema-constrained transport. Engine evidence is required (engine provider, leading engine model prefix, engine brand in the model id, engine host keyword, or an engine-*exclusive* port) so a loopback OpenAI-compatible gateway keeps native tool calling instead of receiving the constrained `response_format` that strict gateways reject with HTTP 400. Ports shared with gateways (`8000`, `8080` — LiteLLM proxy / one-api / vLLM docs) are deliberately excluded, ports are parsed rather than substring-matched, and a lone port with no provider/model identity fails open | ✅ |
| concurrency.py | Core | Concurrency gate — per-model and global asyncio semaphores | ✅ |
| converters.py | Core | Bidirectional message format conversion (LangChain ↔ LiteLLM) with explicit message-name preservation; `convert_dict_to_message` preserves `reasoning_content` into `additional_kwargs` (non-streaming parity with stream path) | ✅ |
| metrics.py | Core | Empty response retry metrics tracking | ✅ |
| safety_termination_detector.py | Core | Detects provider safety terminations and suppresses truncated tool_calls to prevent corrupt dispatch | ✅ |
| schema/ | Core | Outbound tool schema normalization sub-package. `normalizer.py` — `normalize_tool_schema` entry point: `$ref`/`$defs` inlining (incl. OpenAPI 3.x `#/components/schemas/...` pointers and nested path descent like `#/definitions/Foo/properties/bar`; sibling metadata preserved — overriding description/default survive; unresolvable refs — missing definitions, external URL pointers, circular chains past depth 20 — degrade to a permissive schema instead of leaking a bare `$ref` that strict providers 400 on; the `components` container is dropped after resolution), array-form `type` normalization (`normalize_type_arrays` from `scalar_compat.py` runs before composite-keyword logic — `["X", "null"]` → scalar + nullable hint, `["X", "Y"]` → `anyOf`, `["null"]` → `"null"`, `[]` dropped — so Pydantic v1 Optional / old zod output neither crashes missing-type inference nor triggers strict-provider 400), top-level composite handling (single object branch extraction, multi-branch `allOf` conjunctive merge / `anyOf`/`oneOf` alternative merge with exclusivity hint folding, outer metadata preserved onto merged branches), nested property-level `anyOf`/`oneOf` unions of multiple object branches merged so no branch's parameters stay hidden, orphan required pruning (Gemini/strict mode), missing-type inference, enum cleanup. `property_merge.py` — property-level branch merging: `merge_allof_branches` (conjunctive: required union, same-name property `const`/`enum` intersection) vs `merge_union_object_branches` (alternative: required dropped except every-branch-common discriminator promotion + excluded from exclusivity hint, same-name const/enum union, keyword-aware exclusivity hint — oneOf "exactly one group", anyOf "at least one"), `apply_union_hint`, per-property `merge_union_property`/`intersect_property` — branch metadata (title/description/default) merged symmetrically via `_merge_metadata` mirroring inbound union/intersection semantics so no branch's guidance is dropped. `scalar_compat.py` — `normalize_type_arrays`: deterministic, idempotent rewrite of array-form `type` for strict-provider compatibility. `anthropic_strip.py` — Anthropic/Claude-specific unsupported JSON Schema keyword stripping with constraint-to-description folding; `is_anthropic_model` gate. | ✅ |
| stream_aggregator.py | Core | Stream aggregation & XML tag purging; `finalize_stream` exports Responses wire `responses_reasoning_items` on the final yielded chunk for `agenerate_from_stream` | ✅ |
| streaming.py | Core | Streaming response parsing, incremental tool call merging | ✅ |
| native_compaction.py | Core | OpenAI Responses API native server-side compaction bridge DTO, route eligibility gating, and param builder | ✅ |
| tool_call_parsers.py | Core | Tool-call parser facade: stable import surface plus the priority-ordered parse_tool_calls() dispatcher; format implementations live in parsers/ | ✅ |
| parsers/ | Core | Tool-call format parser sub-package (types, openai_format, glm_xml, qwen_xml_json, anthropic_xml, deepseek_inline, deepseek_dsml, leaked_json, json_scanner, text_utils) | ✅ |
| tool_recovery.py | Core | Cross-provider tool call argument recovery with fallback strategies | ✅ |
| wire/ | Core | OpenCode wire transport (responses + anthropic messages). See [wire/_ARCH.md](wire/_ARCH.md). | ✅ |

## Key Dependencies

- `infra`
- `observability`
- `utils`
