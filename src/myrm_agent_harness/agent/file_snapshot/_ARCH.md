# file_snapshot/

## Overview
Workspace file versioning and rollback subsystem. Provides transparent file-level snapshots before file-mutating operations, enabling rollback to any previous state.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Exports FileSnapshotProtocol, stores, factory, types, restore_inbox. | — |
| types.py | Types | SnapshotTrigger enum, FileSnapshotInfo, FileChange, FileDiff, RestoreResult dataclasses. | ✅ |
| protocols.py | Protocol | FileSnapshotProtocol — runtime_checkable Protocol for snapshot operations. | ✅ |
| shadow_git_store.py | Implementation | ShadowGitSnapshotStore — shared bare repo with env-variable isolation (GIT_DIR, GIT_WORK_TREE, GIT_INDEX_FILE). Preferred. | ✅ |
| shadow_git_maintenance.py | Mixin | ShadowGitMaintenance — auto-pruning, orphan detection, repair, oversized workspace validation, project-commit lookup. | ✅ |
| local_store.py | Implementation | LocalFileSnapshotStore — file copy + JSON manifest. Fallback when git is absent. | ✅ |
| factory.py | Factory | create_file_snapshot_store() — auto-selects Shadow Git or Local File based on git availability. | ✅ |
| restore_inbox.py | Notification | In-process deque inbox. Server pushes restore events; agent_runtime drains them as HumanMessage on next turn. | ✅ |
| external_effect_detector.py | Detector | Pure-function regex detector for irreversible external effects (database/container/network mutations). | ✅ |

## Key Dependencies

- `utils.logger_utils`
- stdlib: hashlib, json, shutil, uuid, os, time, asyncio, re
- External: git CLI (optional — fallback to LocalFileSnapshotStore when absent)

## Key Design Decisions

- **Shadow Git over direct git**: Uses GIT_DIR + GIT_WORK_TREE + GIT_INDEX_FILE to isolate from user repos. Never touches user's .git, .gitignore, or git config.
- **Single shared bare repo**: Content-addressable deduplication across projects and turns. Storage path: `{MYRM_DATA_DIR}/file_snapshots/store/`.
- **Per-project isolation**: Each project gets its own ref (`refs/myrm/<hash>`) and index file.
- **Git plumbing commands**: write-tree + commit-tree + update-ref for precise control, bypassing hooks.
- **Full env isolation**: GIT_CONFIG_GLOBAL=/dev/null + GIT_CONFIG_SYSTEM=/dev/null prevents gpgsign and hook interference. `_bare_env()` strips residual GIT_WORK_TREE/GIT_INDEX_FILE to prevent cross-contamination when host process has git env vars set.
- **MYRM_DATA_DIR path derivation**: All storage paths derived from MYRM_DATA_DIR, compatible with SaaS persistent volumes.
- **Auto-maintenance**: Orphan detection, dual-layer pruning (per-project + global size cap), git gc.
- **Factory pattern**: create_file_snapshot_store() auto-detects git and caches the result.
- **Max file size**: 10MB per file to avoid snapshotting large binaries.
- **Max file count**: 50,000 files per workspace to prevent timeouts on oversized directories.
- **Runtime excludes**: `.agent/` (artifact vault) and `.myrm/` (workspace runtime metadata) are excluded from shadow git and local snapshots.
- **Structured commit messages**: Metadata stored as key=value in commit body for reliable parsing.
- **Maintenance mixin separation**: Pruning, repair, and validation logic in ShadowGitMaintenance mixin keeps ShadowGitSnapshotStore under 500 lines.
- **No-change skip**: `git diff-index --cached --quiet` avoids creating redundant commits when no files changed.
- **CAS concurrency safety**: `git update-ref ref new old` prevents concurrent snapshot overwrites.
- **Restore context injection**: `restore_inbox.py` bridges the server restore API and agent_runtime. After GUI rollback, a notification is pushed to the in-process deque; agent_runtime drains it as a HumanMessage at the end of the messages list (preserving prompt cache prefix). 600s TTL auto-expires stale notifications.
- **External effect detection**: `external_effect_detector.py` detects bash commands that produce state changes file-rollback cannot undo (DB mutations, container/cloud ops, HTTP writes). Stored as `metadata.external_effects` in commit trailers. Frontend shows ⚠️ badge; Agent receives warning in restore notification.
