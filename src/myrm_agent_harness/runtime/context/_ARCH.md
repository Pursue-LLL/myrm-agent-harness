# context/

## Overview
Context lifecycle management — cleanup, config, metrics, tracking, reading, offload.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Context lifecycle management — cleanup, config, metrics, tracking, reading, offload. | — |
| archive_restore_action.py | Core | Typed GUI/server archive restore action contract: validates current-session archive path, explicit line range and restore budget, then streams the requested range into bounded XML context for the next Agent turn and returns UI-safe restore result metadata; late line ranges build/reuse a sparse byte-offset sidecar so repeated restores do not rescan from file start. | ✅ |
| archive_store.py | Core | Session-scoped content-addressed archive storage for retry-safe tool-result offload reuse, atomic payload/metadata writes, restore-map sidecar generation/self-healing, and metadata/payload hash validation before reuse. | ✅ |
| cleanup.py | Core | Context file cleanup with session-aware strategy. | ✅ |
| cleanup_ops.py | Core | Context cleanup entrypoints for session directory cleanup and orphan cleanup. | ✅ |
| cleanup_task.py | Core | Background task: periodically clean up orphaned context files. | ✅ |
| config.py | Config | Context management configuration. | ✅ |
| file_access_tracker.py | Core | File access tracking system for context files. | ✅ |
| instance_metrics.py | Core | Context operation metrics for monitoring and observability. | ✅ |
| offload.py | Core | Context offload: persist full tool outputs and conversation snapshots through framework-neutral scope IDs, with lifecycle access tracking and cleanup entrypoint re-exports. | ✅ |
| restore_map_contract.py | Core | Shared restore-map schema v2 contract reader/writer for archive writers and restore guidance, including path normalization and line-range validation. | ✅ |
| restore_map_structures.py | Core | Restore-map structural indexing and UI-safe restore metadata construction: content indexes, source-tagged recommended ranges, range-source hints, and bounded content feature summaries. | ✅ |
| session_activity.py | Core | Session activity loading for context lifecycle management. | ✅ |
| tracker_manager.py | Core | Generic singleton manager for tracker instances. | ✅ |
| transparent_reader.py | Core | Transparent decompression for context files. | ✅ |

## Key Dependencies

- `agent`
- `toolkits`
