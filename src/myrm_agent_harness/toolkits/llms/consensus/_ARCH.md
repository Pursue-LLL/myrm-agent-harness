# consensus/

## Overview
Multi-model consensus (MoA) inference engine. Parallel-queries multiple
reference LLMs on the same prompt, then synthesises all responses through
an aggregator LLM. Based on arXiv:2406.04692.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Re-exports ConsensusEngine, ConsensusStreamEvent, ConsensusConfig, ConsensusResult, ReferenceResponse | — |
| types.py | Config | Immutable data types: ConsensusConfig, ReferenceResponse, ConsensusResult | ✅ |
| _prompts.py | Helper | Aggregation prompt: `AGGREGATOR_SYSTEM` + `build_aggregation_messages()` (stateless, persona-aware) | ✅ |
| _streaming.py | Helper | `collect_stream()`: stream one model → string with reasoning fallback + per-call temperature; shared by references and aggregator | ✅ |
| engine.py | Core | Stateless consensus orchestration: `run()` batch, `run_stream()` streaming; fan-out / retry / timeout / cancel, single-reference skip, graceful degradation. Delegates prompt building to `_prompts`, stream collection to `_streaming` | ✅ |

## Key Design Decisions

- **Accepts BaseChatModel**: any LangChain-compatible LLM works (ChatLiteLLM, KeyPoolLLM, ManagedLLM).
- **Stateless**: no shared state between runs; create one engine per consensus request or reuse across calls.
- **Graceful degradation**: when the aggregator fails before emitting anything, falls back to the longest reference response. On a *mid-stream* failure (some synthesis already streamed), the partial output is kept as-is — splicing a full raw reference onto half-written synthesis would corrupt the answer.
- **Single-reference skip**: when exactly one reference succeeds (e.g. `min_successful=1` with the rest failing), `run()`/`run_stream()` return that answer verbatim and skip the aggregator entirely — saving one model call and preventing the aggregator's "do not simply repeat" instruction from rewording an already-correct lone answer.
- **Persona-faithful synthesis**: the aggregated answer is streamed straight to the user as the final reply, so `run()`/`run_stream()` thread the agent `system_prompt` into `build_aggregation_messages` as well — not only into the reference calls. The persona is prepended ahead of `AGGREGATOR_SYSTEM`, keeping a cacheable static prefix (`persona` + synthesis instruction are stable per agent; the per-request reference answers follow and stay dynamic). Without this the synthesis would silently drop the configured persona, language and format. When no `system_prompt` is supplied the prompt is unchanged, so caching for persona-less agents is unaffected.
- **Temperature separation**: reference models sample hotter (`reference_temperature`, default 0.6) for diverse perspectives, the aggregator colder (`aggregator_temperature`, default 0.4) for focused synthesis. The engine binds temperature per call (`llm.bind(temperature=...)`) rather than mutating the shared, cached model instance; `litellm.drop_params` silently ignores it for models that reject a custom temperature. The reference/aggregator models themselves are injected as `BaseChatModel` instances, so `ConsensusConfig` only carries execution parameters, not model identifiers.
- **Reasoning-content fallback**: both the per-call collector (`collect_stream` in `_streaming.py`, used by references and the batch aggregator) and the streaming aggregator (`_aggregate_stream`) fall back to a chunk's `reasoning_content` when `content` is empty, so reasoning models (DeepSeek-R1, GLM) that stream their answer there are not discarded as empty. `collect_stream` returns the buffered reasoning only when no `content` arrived; `_aggregate_stream` streams `content` token-by-token but, when a run yields no `content` at all, flushes the buffered reasoning once at the end. Without this the streaming aggregator would emit nothing and `run_stream` would silently degrade to the longest raw reference, losing the synthesis — the common case where a reasoning model is the default aggregator.
- **Cancel support**: `cancel_token` checked before each phase (references, aggregation) to abort early.
- **Streaming aggregation**: `run_stream()` yields `ConsensusStreamEvent` with per-token aggregator output for real-time UX.
- **Cost attribution via streaming**: every model call — references and aggregator, in both `run()` and `run_stream()` — is consumed with `astream`, because the LLM adapter records per-call token usage and cost into the request-scoped token tracker only on its streaming path. The caller (e.g. the server consensus lane) owns the tracker lifecycle (`init_token_tracker` → run → read `to_dict()` → `reset_token_tracker`), since consensus bypasses the agent runtime that normally manages it.
