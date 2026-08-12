# infra/

## Overview
Context management infrastructure: shared types, budget management, session locks, and optional cache metrics persistence.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Context management infrastructure: shared types, budget management, session locks, and optional cache metrics persistence. | — |
| cache_break_detector.py | Core | Prompt cache break detection and attribution. Detects cache drops and attributes to system prompt change, tool schema change, model switch, or TTL expiry. Works with ``toolkits/mcp/schema.normalize.canonicalize_schema_for_cache`` to form a prevention+detection closed loop. | ✅ |
| archive_reference.py | Core | Structured archive references and restore contracts for offloaded context payloads, including lightweight line/chunk, JSON, Markdown, code block, table, and list indexes plus chunk restore args for targeted recovery. | ✅ |
| cache_policy.py | Core | Framework-level prompt cache policy profile resolution for context pruning with provider TTL calibration metadata. | ✅ |
| cache_metrics_collector.py | Core | Request-scoped pairing via ContextVar (same asyncio task as token tracker). | ✅ |
| context_budget.py | Core | Context budget via estimate_context_tokens; resolve_budget_kwargs_from_metadata + estimate_processor_context_tokens for pipeline SSOT; DEFAULT_ESTIMATED_REMAINING_TURNS shared by runtime + preflight dynamic threshold. | ✅ |
| message_priority.py | Core | Message priority classification for intelligent compression. | ✅ |
| resume_validator.py | Core | Resume-from-interrupt validator. Verifies that the current Agent config matches the config saved in  | — |
| schemas.py | Config | Context management shared data structures. Defines CacheUsageFeedback, ContextOffloadResult, compact format types, summary schemas, cache-TTL emergency prune ratio, restore-cost backoff thresholds, large-payload fast guard threshold, ContextConfig (including user-configurable compress_start_ratio for per-agent threshold tuning), and config | ✅ |
| schemas_pre_compact.py | Config | PreCompactInjection + ContextPreCompactCallback types | ✅ |
| session_lock.py | Core | Session-level lock manager. Provides reentrant per-session async locks for serialized context mutations while preserving cross-session parallelism. | ✅ |
| retention_helpers.py | Core | Shared retention helpers: compression_intent extraction (failed/focus/goal), group-aware focus matching via tool_call_id index, keep_recent prune cutoff, deterministic retain trim formatting | ✅ |
| tool_result_trimming.py | Core | Deterministic trimming for oversized tool outputs. Uses structure-aware JSON compaction under the fast-guard threshold and bounded head/tail text trim above it. | ✅ |
| tool_output_persister.py | Core | UECD delegate — persists FilterProcessor overflows to `.context/.../evicted/` | ✅ |
| evicted_content.py | Core | UECD SSOT: 2MB cap, `{source}_{hex8}.{ext}` naming, persist/footer; `EvictedRefPayload` + `emit_evicted_ref` SSE contract (`tool_call_id`, stats fields); `normalize_delivery_chat_id`; server `evicted.py` imports `EVICTED_BASENAME_PATTERN` | ✅ |
| evicted_reader.py | Core | Streaming line-range + meta readers for `.context/.../evicted/` files (GUI/API pagination SSOT) | ✅ |

## Key Dependencies

- `infra`
- `utils`
