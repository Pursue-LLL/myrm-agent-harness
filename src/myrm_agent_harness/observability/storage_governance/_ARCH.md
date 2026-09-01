# storage_governance/

## Overview
Subsystem for Agent persistent state storage governance, space inspection, safe non-blocking compaction, and snapshot-based disaster recovery/rollback.

## File Index

| File | Role | Description |
|------|------|-------------|
| `__init__.py` | Package | Re-exports core inspection, compaction, and snapshot management APIs. |
| `types.py` | Core | Data models and contracts (`StorageGovernanceReport`, `CompactionResult`, `StateSnapshotMetadata`). |
| `inspector.py` | Core | `StorageGovernanceInspector` for per-category and SQLite table-level space attribution. |
| `compactor.py` | Core | `StateStorageCompactor` executing non-blocking incremental vacuum, WAL truncation, and orphan cleanup. |
| `snapshot_manager.py` | Core | `StateSnapshotManager` supporting point-in-time state checkpointing and atomic rollback. |
