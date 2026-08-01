# processors/

## Overview
Pipeline processors module.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Pipeline processors module. | — |
| active_tool_result_prune_processor.py | Core | Per-step active pruning of large tool results from earlier steps. Replaces results exceeding threshold (default 2048 tokens) with archive placeholders at zero LLM cost. Records `active_tool_prune` compression events via TaskMetrics. Positioned after FilterProcessor, before CacheTtlPruneProcessor. | ✅ |
| cache_breakpoint_validator.py | Core | Validates breakpoints against provider constraints: | ✅ |
| cache_optimizer.py | Core | ExplicitCacheProcessor for Anthropic/Qwen: 4-strategy breakpoints, 20-block window protection, endpoint-aware TTL (1h for direct API/LiteLLM anthropic routing, 5min for proxies). | ✅ |
| cache_ttl_prune_processor.py | Core | Provides CacheTtlPruneProcessor for token-aware pruning with adaptive backoff and delegates archive-summary checkpoints to injected `ArchiveSummaryService`. | ✅ |
| cache_ttl_prune_helpers.py | Internal | Cache TTL pruning helper layer. Keeps DTOs, archive write/reuse counters, pure content conversion, archive placeholder rendering, and message replacement helpers outside the processor orchestration file. | ✅ |
| compress_processor.py | Core | Provides CompressProcessor with Hot Cache Bypass and Anti-Thrashing protection. | ✅ |
| filter_processor.py | Core | LLM semantic filter for oversized single tool outputs; skips LLM summary for failed-tool IDs, tool errors, and focus/goal tool-call groups via retention_helpers (structure trim only). Only truncates individual messages exceeding `tool_result_evict_threshold`; does NOT apply aggregate truncation (removed for prompt cache stability). | ✅ |
| media_filter.py | Core | Proactive media filter — strips image/video/audio for text-only models before LLM call. | ✅ |
| vision_fallback_processor.py | Core | Converts surviving image blocks to text via VisionFallbackEngine capacity failover chain (`vision_fallback_model_cfgs` / cfg) when primary model is text-only. Runs immediately before MediaFilterProcessor. Resolves non-base64 `/api/media` URLs via injected `file_content_reader`. Shared `apply_vision_fallback_to_messages` is also used by stream recovery on MEDIA_REJECTED. | ✅ |
| media_resolver.py | Core | Resolves non-base64 image URLs (HTTP/file/API references) to base64 data URLs right before LLM invocation. Supports `file://` local paths, HTTP(S) StorageProvider URLs, and `/api/media/` paths via injected `FileContentReader`. Positioned after MediaFilter so only surviving images are resolved. | ✅ |
| normalize_processor.py | Core | Provides NormalizeProcessor. | ✅ |
| post_compaction_reread_processor.py | Core | Post-compaction active file reread. After compaction (tokens_saved > 0), reads top-5 recently modified files from ArtifactTracker and injects their content as HumanMessage, eliminating redundant read_file tool calls. | ✅ |
| post_compaction_refetch_guard_processor.py | Core | One-shot tail hint when repeated archive restores for the same path are detected after compaction (anti refetch loop). | ✅ |
| session_notes_processor.py | Core | Provides SessionNotesProcessor. | ✅ |
| summarize_processor.py | Core | Provides SummarizeProcessor with progress-aware timeout guard (`_guarded_summarize`), cancellation-safe task cleanup via `finally` block, and frontend lifecycle event emission (3s debounce → active heartbeat → timeout/fallback/completed). | ✅ |
| pre_compact_processor.py | Core | Pre-compaction semantic memory recall processor. Invokes ContextPreCompactCallback before Compress/SessionNotes/Summarize and stores protected HumanMessage recall in context metadata. | ✅ |
| thinking_cleaner.py | Core | Provides ThinkingBlockCleaner: three-scope cleanup — (1) strips content thinking/redacted_thinking blocks from non-latest assistant turns, (2) removes reasoning_content from additional_kwargs per-provider (Anthropic always; DeepSeek/MiMo/Kimi on plain-text before last user turn), (3) removes thinking_blocks from additional_kwargs for non-Anthropic models. | ✅ |

## Key Dependencies

- `observability`
- `utils`
