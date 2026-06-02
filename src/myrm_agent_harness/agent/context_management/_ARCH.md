# context_management/

## Overview
Context management module. Prompt cache practice (break attribution, skill catalog vs SystemMessage) documented in [PROMPT_CACHE_PRACTICE.md](PROMPT_CACHE_PRACTICE.md).

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Context management module. | — |
| context.py | Core | Agent runtime context definition. Provides a type-safe context container for passing user, session,  | ✅ |
| preheat.py | Utility | Prefix cache preheat after idle compression. Sends max_tokens=1 probe to warm provider's prefix cache for explicit-cache providers (Anthropic, Qwen). | ✅ |

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
