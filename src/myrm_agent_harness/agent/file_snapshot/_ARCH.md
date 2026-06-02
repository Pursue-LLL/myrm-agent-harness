# file_snapshot/

## Overview
Workspace file versioning and rollback subsystem. Provides transparent file-level snapshots before file-mutating operations, enabling rollback to any previous state.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Exports FileSnapshotProtocol, FileSnapshotInfo, FileDiff, RestoreResult, SnapshotId. | — |
| types.py | Types | SnapshotTrigger enum, FileSnapshotInfo, FileChange, FileDiff, RestoreResult dataclasses. | ✅ |
| protocols.py | Protocol | FileSnapshotProtocol — runtime_checkable Protocol for snapshot operations. | ✅ |
| local_store.py | Implementation | LocalFileSnapshotStore — file copy + JSON manifest storage at .myrm/snapshots/. | ✅ |
| auto_interceptor.py | Interceptor | AutoSnapshotInterceptor — transparent per-turn dedup snapshot before file-mutating tools. | ✅ |

## Key Dependencies

- `utils.logger_utils`
- stdlib: hashlib, json, shutil, uuid, os, time

## Key Design Decisions

- **File copy over git shadow**: No external dependency, works without git repository
- **Per-turn dedup**: Same workspace within one conversation turn only snapshots once (matches Hermes checkpoint_manager pattern)
- **Pre-rollback snapshot**: Every restore automatically takes a snapshot before overwriting
- **Auto-cleanup**: Keeps max 20 snapshots per workspace, prunes oldest
- **Exclude patterns**: .git, node_modules, .venv, __pycache__, .myrm, dist, build, etc.
- **Max file size**: 10MB per file to avoid snapshotting large binaries
