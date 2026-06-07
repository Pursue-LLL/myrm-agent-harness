# infra/

## Overview
Context management infrastructure: shared types, budget management, session locks, and optional cache metrics persistence.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Context management infrastructure: shared types, budget management, session locks, and optional cache metrics persistence. | — |
| cache_break_detector.py | Core | Prompt cache break detection and attribution. Detects cache drops and attributes to system prompt change, tool schema change, model switch, or TTL expiry. Works with ``toolkits/mcp/schema_utils.canonicalize_schema_for_cache`` to form a prevention+detection closed loop. | ✅ |
| archive_reference.py | Core | Structured archive references and restore contracts for offloaded context payloads, including lightweight line/chunk, JSON, Markdown, code block, table, and list indexes plus chunk restore args for targeted recovery. | ✅ |
| cache_policy.py | Core | Framework-level prompt cache policy profile resolution for context pruning with provider TTL calibration metadata. | ✅ |
| cache_metrics_collector.py | Core | Request-scoped pairing via ContextVar (same asyncio task as token tracker). | ✅ |
| context_budget.py | Core | Provides ContextHealthStatus, ContextBudget, calculate_context_budget. | ✅ |
| message_priority.py | Core | Message priority classification for intelligent compression. | ✅ |
| resume_validator.py | Core | Resume-from-interrupt validator. Verifies that the current Agent config matches the config saved in  | — |
| schemas.py | Config | Context management shared data structures. Defines CacheUsageFeedback, ContextOffloadResult, compact format types, summary schemas, cache-TTL emergency prune ratio, restore-cost backoff thresholds, large-payload fast guard threshold, PreCompactInjection/ContextPreCompactCallback, ContextConfig (including user-configurable compress_start_ratio for per-agent threshold tuning), and config | ✅ |
| session_lock.py | Core | Session-level lock manager. Provides reentrant per-session async locks for serialized context mutations while preserving cross-session parallelism. | ✅ |
| tool_result_trimming.py | Core | Deterministic trimming for oversized tool outputs. Uses structure-aware JSON compaction under the fast-guard threshold and bounded head/tail text trim above it. | ✅ |
| tool_output_persister.py | Core | Large tool output persister. | ✅ |

## Key Dependencies

- `infra`
- `utils`
