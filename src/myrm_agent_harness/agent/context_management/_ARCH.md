# context_management/

## Overview
Context management module. Industry theory: [CONTEXT_ENGINEERING.md](CONTEXT_ENGINEERING.md). Prompt cache practice: [PROMPT_CACHE_PRACTICE.md](PROMPT_CACHE_PRACTICE.md).

Detailed design: [CONTEXT_MANAGEMENT_SYSTEM.md](CONTEXT_MANAGEMENT_SYSTEM.md)

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| CONTEXT_ENGINEERING.md | L2 | Industry context-engineering theory (Manus, Anthropic, Factory Research) | — |
| CONTEXT_MANAGEMENT_SYSTEM.md | L2 | Detailed context-management system design (processor chain, compression pipeline, retention) | — |
| PROMPT_CACHE_PRACTICE.md | L2 | Framework prompt-cache implementation practices | — |
| __init__.py | Package | Context management module. | — |
| context.py | Core | Agent runtime context definition. Provides a type-safe context container for passing user, session,  | ✅ |
| preheat.py | Utility | Prefix cache preheat and idle keep-alive for explicit-cache providers (Anthropic, Qwen). Three patterns: agent-init preheat (`schedule_init_preheat`), post-compaction re-warming (`preheat_prefix_cache`), and idle keep-alive (`CacheKeepAliveManager` — periodic 4-min probes to prevent 5-min TTL eviction). Uses max_tokens=0 per Anthropic best practice with max_tokens=1 fallback. | ✅ |
| pre_compact_service.py | Core | MemoryPreCompactService — default ContextPreCompactCallback; semantic recall before compaction. | ✅ |
| salient_tool_filter.py | Utility | Deterministic Salient Tool Output Filter & Verbatim Evidence Extractor for preserving high-severity tool outputs before context compaction without LLM cost. | ✅ |

| Submodule | Description |
|-----------|-------------|
| archive_checkpoint/ | Lite-LLM archive summary checkpoints: Protocol store, EpisodicMemory persistence, bounded async `ArchiveSummaryService`. |
| downshift/ | Context threshold model downshift governor and deterministic handover memo protocol (token % and WU dual triggers, zero-API SessionNotes extraction, Fallback-Up circuit breaker). |
| infra/ | Context management infrastructure: shared types, token estimation, budget management, session locks, archive references, cache policy. |
| pipeline/ | Ordered context processors for filtering, active per-step tool-result pruning, cache-TTL pruning, pre-compaction recall, compression, session notes, summarization, post-compaction refetch guard, normalization, and explicit cache markers. Filter and Compress consume compression_intent via retention_helpers. |
| strategies/ | Three-tier context reduction strategies: Filter, Compress, Summarize. `Summarize` enforces structural validation via `with_structured_output` to eliminate JSON parsing fragility. |
| tracking/ | Observation and tracking: artifact tracking, task metrics, archive refetch cost, restore-block events, and archive read budgets. |

## Key Dependencies

- `agent` (types, event_log)
- `infra` (delivery, tracing)
- `utils` (token_economics)
