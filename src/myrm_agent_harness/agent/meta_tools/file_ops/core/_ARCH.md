# core/

## Overview
Text Editor core business logic module.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Text Editor core business logic module. | — |
| archive_restore_guard.py | Core | Archive restore read guard. Blocks oversized full archive restores before loading contents, formats structured blocked payloads, and parses that payload for runtime status events. | ✅ |
| batch_str_replace.py | Core | Batch str-replace engine. In-memory sequential apply with overlap precheck before single disk write. | ✅ |
| file_conflict_guard.py | Core | File edit conflict guard. Calculates affected line ranges and blocks overlapping concurrent subagent edits. | ✅ |
| file_path_lock_manager.py | Core | Per-path asyncio lock manager for write serialization (canonical realpath+normcase identity; same file aliases serialize, disjoint paths parallel). | ✅ |
| file_operation_service.py | Core | File operation service; vault markdown FM preserve + Office text-write warnings on CREATE/STR_REPLACE; CREATE over existing path notifies modified (pre/post disk) not created; archive context reads enforce session ownership, pre-read full-restore budgets, range-aware restore budgets, and structured blocked payloads before exposing content; anchors CAS version checks with edit target candidates for centered conflict rebasing. | ✅ |
| operation_context.py | Core | Provides OperationType, ViewRange, OperationContext. | ✅ |
| read_semaphore.py | Core | Event-loop scoped read semaphore registry for concurrent file read limits. | ✅ |
| result_formatter.py | Core | Provides FileContent, DirectoryListing, ResultFormatter. | ✅ |
| file_integrity_guard.py | Core | File integrity guard. Read-before-write gate (hard reject), full-read gate before edits, and content-hash version gate with two-tier anchor locator (exact match + signature line fallback) and candidate sequence support for context-centered self-healing preview payload on external modification; advances known hash on conflict rejection to eliminate infinite CAS rejection loops and guarantee 1-turn direct rebase. Agent-aware with per-agent tracking. Partial reads use a sentinel marker. | ✅ |
| file_activity_tracker.py | Core | File activity tracker. Line-level conflict detection for concurrent subagent file operations. | ✅ |
| file_edit_normalizer.py | Util | LLM input normalizer for file_edit_tool legacy flat fields（`normalize_edits_payload`、`merge_edits_for_diff`） | ✅ |
| file_read_handlers.py | Internal | Multimodal/text/vault execution handlers for file_read_tool | ✅ |
| file_read_truncation.py | Internal | Output truncation helpers for file_read_tool. Complete-line-boundary head truncation with precomputed next_offset and line-count cap. | ✅ |
| file_read_outline.py | Internal | Adaptive structural outline extractor (Markdown headings, code symbols, classes/functions with line ranges) for truncated reads and structure mode. | ✅ |
| read_dedup.py | Core | Read dedup guard. Skips re-reading unchanged local files to protect Prompt Cache; stub + hard-block escalation, write invalidation, compression reset, env kill-switch. Agent-aware per-agent buckets. | ✅ |
| mcp_read_next_step_hint.py | Util | One-shot MCP workflow reminder appended after batch-read of function docs | ✅ |

## Key Dependencies

- `backends`
- `toolkits`
- `utils`
