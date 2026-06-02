# core/

## Overview
Text Editor core business logic module.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Text Editor core business logic module. | — |
| archive_restore_guard.py | Core | Archive restore read guard. Blocks oversized full archive restores before loading contents, formats structured blocked payloads, and parses that payload for runtime status events. | ✅ |
| file_conflict_guard.py | Core | File edit conflict guard. Calculates affected line ranges and blocks overlapping concurrent subagent edits. | ✅ |
| file_operation_service.py | Core | File operation service; CREATE over existing path notifies modified (pre/post disk) not created; archive context reads enforce session ownership, pre-read full-restore budgets, range-aware restore budgets, and structured blocked payloads before exposing content. | ✅ |
| operation_context.py | Core | Provides OperationType, ViewRange, OperationContext. | ✅ |
| read_semaphore.py | Core | Event-loop scoped read semaphore registry for concurrent file read limits. | ✅ |
| result_formatter.py | Core | Provides FileContent, DirectoryListing, ResultFormatter. | ✅ |
| staleness_guard.py | Core | File integrity guard. Combines read-before-edit gate (hard reject for unread files) with content-hash staleness detection (soft warning for externally modified files). Agent-aware with per-agent tracking. Sentinel value marks partial reads that pass the gate but skip staleness check. | ✅ |
| file_activity_tracker.py | Core | File activity tracker. Line-level conflict detection for concurrent subagent file operations. | ✅ |

## Key Dependencies

- `backends`
- `toolkits`
- `utils`
