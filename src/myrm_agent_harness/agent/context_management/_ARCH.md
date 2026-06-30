# context_management/

## Overview
Context management module. Industry theory: [CONTEXT_ENGINEERING.md](CONTEXT_ENGINEERING.md). Prompt cache practice: [PROMPT_CACHE_PRACTICE.md](PROMPT_CACHE_PRACTICE.md).

Detailed design: [CONTEXT_MANAGEMENT_SYSTEM.md](CONTEXT_MANAGEMENT_SYSTEM.md)

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| CONTEXT_ENGINEERING.md | L2 | Industry context-engineering theory (Manus, Anthropic, Factory Research) | — |
| PROMPT_CACHE_PRACTICE.md | L2 | Framework prompt-cache implementation practices | — |
| __init__.py | Package | Context management module. | — |
| context.py | Core | Agent runtime context definition. Provides a type-safe context container for passing user, session,  | ✅ |
| preheat.py | Utility | Prefix cache preheat for explicit-cache providers (Anthropic, Qwen). Agent-init preheat (fire-and-forget at startup via `schedule_init_preheat`) and `preheat_prefix_cache` API for post-compaction re-warming. Uses max_tokens=0 per Anthropic best practice with max_tokens=1 fallback. | ✅ |
| pre_compact_service.py | Core | MemoryPreCompactService — default ContextPreCompactCallback; semantic recall before compaction. | ✅ |

| Submodule | Description |
|-----------|-------------|
| archive_checkpoint/ | Lite-LLM archive summary checkpoints: Protocol store, EpisodicMemory persistence, bounded async `ArchiveSummaryService`. |
| infra/ | Context management infrastructure: shared types, token estimation, budget management, session locks, archive references, cache policy. |
| pipeline/ | Ordered context processors for filtering, cache-TTL pruning, pre-compaction recall, compression, session notes, summarization, normalization, and explicit cache markers. |
| strategies/ | Three-tier context reduction strategies: Filter, Compress, Summarize. `Summarize` enforces structural validation via `with_structured_output` to eliminate JSON parsing fragility. |
| tracking/ | Observation and tracking: artifact tracking, task metrics, archive refetch cost, restore-block events, and archive read budgets. |

## Key Dependencies

- `agent` (types, event_log)
- `infra` (delivery, tracing)
- `utils` (token_economics)
