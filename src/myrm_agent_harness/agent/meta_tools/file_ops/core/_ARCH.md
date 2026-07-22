# core/

## Overview
Text Editor core business logic module.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Text Editor core business logic module. | — |
| archive_restore_guard.py | Core | Archive restore read guard. Blocks oversized full archive restores before loading contents, formats structured blocked payloads, and parses that payload for runtime status events. | ✅ |
| file_conflict_guard.py | Core | File edit conflict guard. Calculates affected line ranges and blocks overlapping concurrent subagent edits. | ✅ |
| file_path_lock_manager.py | Core | Per-path asyncio lock manager for write serialization (canonical realpath+normcase identity; same file aliases serialize, disjoint paths parallel). | ✅ |
| file_operation_service.py | Core | File operation service; CREATE over existing path notifies modified (pre/post disk) not created; archive context reads enforce session ownership, pre-read full-restore budgets, range-aware restore budgets, and structured blocked payloads before exposing content. | ✅ |
| operation_context.py | Core | Provides OperationType, ViewRange, OperationContext. | ✅ |
| read_semaphore.py | Core | Event-loop scoped read semaphore registry for concurrent file read limits. | ✅ |
| result_formatter.py | Core | Provides FileContent, DirectoryListing, ResultFormatter. | ✅ |
| file_integrity_guard.py | Core | File integrity guard. Read-before-write gate (hard reject), full-read gate before edits, and content-hash version gate (hard reject on external modification). Agent-aware with per-agent tracking. Partial reads use a sentinel marker. | ✅ |
| file_activity_tracker.py | Core | File activity tracker. Line-level conflict detection for concurrent subagent file operations. | ✅ |

## Key Dependencies

- `backends`
- `toolkits`
- `utils`
