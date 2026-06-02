# processors/

## Overview
Pipeline processors module.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Pipeline processors module. | — |
| cache_breakpoint_validator.py | Core | Validates breakpoints against provider constraints: | ✅ |
| cache_optimizer.py | Core | ExplicitCacheProcessor for Anthropic/Qwen: 4-strategy breakpoints, 20-block window protection, endpoint-aware TTL (1h for direct API/LiteLLM anthropic routing, 5min for proxies). | ✅ |
| cache_ttl_prune_processor.py | Core | Provides CacheTtlPruneProcessor for token-aware pruning with adaptive backoff and delegates archive-summary checkpoints to injected `ArchiveSummaryService`. | ✅ |
| cache_ttl_prune_helpers.py | Internal | Cache TTL pruning helper layer. Keeps DTOs, archive write/reuse counters, pure content conversion, archive placeholder rendering, and message replacement helpers outside the processor orchestration file. | ✅ |
| compress_processor.py | Core | Provides CompressProcessor with Hot Cache Bypass and Anti-Thrashing protection. | ✅ |
| filter_processor.py | Core | Provides FilterProcessor. | ✅ |
| media_filter.py | Core | Proactive media filter — strips image/video/audio for text-only models before LLM call. | ✅ |
| normalize_processor.py | Core | Provides NormalizeProcessor. | ✅ |
| session_notes_processor.py | Core | Provides SessionNotesProcessor. | ✅ |
| summarize_processor.py | Core | Provides SummarizeProcessor. | ✅ |
| pre_compact_processor.py | Core | Pre-compaction semantic memory recall processor. Invokes ContextPreCompactCallback before Compress/SessionNotes/Summarize and stores protected HumanMessage recall in context metadata. | ✅ |
| thinking_cleaner.py | Core | Provides ThinkingBlockCleaner: selective reasoning_content cleanup (tool_calls-aware, per-provider). Anthropic → remove reasoning_content; DeepSeek/MiMo/Kimi → remove reasoning_content from plain-text msgs before last user turn, preserve on tool-call msgs. | ✅ |

## Key Dependencies

- `observability`
- `utils`
