# Prompt Cache Placement (SSOT)

Placement rules for **where dynamic context may appear** relative to the provider prefix cache. Implementation detail lives in [PROMPT_CACHE_PRACTICE.md](../src/myrm_agent_harness/agent/context_management/PROMPT_CACHE_PRACTICE.md).

## Provider serialize order

Most chat APIs materialize requests as:

```text
Tool definitions → System prompt → Messages (oldest → newest)
```

Prefix cache matches from the start of that byte stream. Anything that changes **earlier** in the stream invalidates cache for everything after it.

## What stays in the frozen prefix

| Content | Placement | Rationale |
|---------|-----------|-----------|
| Tool schemas | Front (sorted by layer/name) | See `ToolLayer` / registry in PROMPT_CACHE_PRACTICE §2.1 |
| System prompt | System message, append-only | Do not inject time, memory, or tool results here |
| Stable project / persona blocks | Tier-1 static blocks | `prefix_caching_aligned_layout_engine.py` Tier-1 hash |

## What must NOT be in the system prompt

| Dynamic content | Placement in Myrm harness |
|-----------------|---------------------------|
| Wall-clock / timezone | Trailing segment on **HumanMessage** (see PROMPT_CACHE_PRACTICE §2.2) |
| Retrieved memory brief | Middleware tail / human augmentation; SSE preview marks `injected_in_turn_prefix: false` in server `memory_brief.py` |
| Ephemeral session deltas (LWW) | Final **HumanMessage** tail inside `<ephemeral_session_deltas>`; includes a short `<precedence>` line so deltas override stable memory on conflict (`ephemeral_delta/tail_injector.py`) |
| Two-layer base context (cadence) | Final **HumanMessage** tail `<base_context>` via `two_layer_context_middleware.py` (Layer 2 dialectic off on live path) |
| Tool results | Message history only; never rewrite prior turns to “refresh” memory |
| User instructions / channel delivery | Human-side injection per PROMPT_CACHE_PRACTICE §2.4–2.5 |

## Metrics (measured vs layout)

Do **not** equate “stable layout” with “100% cache hit”. Observe provider usage:

| Field / surface | Source |
|-----------------|--------|
| `cache_read_input_tokens`, `cache_creation_input_tokens` | Provider usage on completion |
| `gen_ai.usage.cache_read_tokens` | OTLP span attributes in `toolkits/llms/adapters/chat_model/async_mixin.py` |
| Session trace `prompt_cache_hit_ratio` | `myrm-agent-server` `session_trace_enrichment.py` (`total_cache_read_tokens / total_prompt_tokens`) |
| `TokenTracker` / `compute_prompt_cache_stats` | `utils/token_economics/tracker.py`, `cache_economics.py` |
| Ephemeral delta API | Layout only: delta count, system hash from preview inject, injection latency—**no** provider hit ratio |

## Product surfaces (SSOT)

| Surface | User | Cache hit rate |
|---------|------|----------------|
| Chat `ContextUsageIndicator` | All GUI users | **Yes** — `health.cache.cache_hit_rate` from provider usage |
| Session trace / OTLP | Ops, analytics | **Yes** — `prompt_cache_hit_ratio` / `cache_read_*` |
| Memory command center ephemeral metrics | Advanced / session overrides | **No** — layout & in-flight delta count only; do not show fake percentages |
| **Two-layer Layer 1 (Item 112)** live chat | All GUI users (GeneralAgent) | **No** — tail layout only; hit rate from chat ring / provider usage. Wired via `two_layer_context_middleware` after ephemeral in `general_agent/factory.py`. Set `MYRM_TWO_LAYER_CONTEXT_LIVE=0` to disable. |
| Memory command center **Two-layer studio (Item 112)** | Lab / API preview only (`NEXT_PUBLIC_MEMORY_LABS=1`) | **No** — cadence/dialectic experiments; not required for live tail. |
| Settings → Runtime snapshot | Local / desktop ops | **N/A** — liveness & memory pressure (`GET /api/v1/ops/snapshot`); not cache hit rate |

## Product copy

User-facing text should describe **prefix stability** and **measured** hit ratios where data exists. Avoid absolute guarantees (“100% hit”, “guaranteed cache”).

## Related code index

- Explicit `cache_control` breakpoints: `toolkits/llms/core/llm.py`
- Roll-forward / preheat: `preheat.py`, `prompt_cache_roll_forward/`
- Break detection: `agent/context_management/infra/cache_break_detector.py`, `agent/context_management/infra/cache_metrics_collector.py`
