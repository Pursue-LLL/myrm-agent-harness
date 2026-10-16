# storage_governance/

## Overview
Subsystem for Agent persistent state storage governance, space inspection, safe non-blocking compaction, and snapshot-based disaster recovery/rollback.

## File Index

| File | Role | Description |
|------|------|-------------|
| `__init__.py` | Package | Re-exports core inspection, compaction, and snapshot management APIs. |
| `types.py` | Core | Data models and contracts (`StorageGovernanceReport`, `CompactionResult`, `StateSnapshotMetadata`). |
| `inspector.py` | Core | `StorageGovernanceInspector` for per-category and SQLite table-level space attribution. The checkpoint database lives wherever the application configures it, so it is attributed through the explicit `checkpoints_db` path (file sizes only; row counts would scan it). |
| `compactor.py` | Core | `StateStorageCompactor` executing WAL truncation plus incremental vacuum (or `PRAGMA optimize`) on the state database; reports the footprint of that database and whether the WAL could really be truncated. Checkpoint history is reclaimed by `runtime/checkpointing/pruning.py`, never here. |
| `snapshot_manager.py` | Core | `StateSnapshotManager` supporting point-in-time state checkpointing and atomic rollback. |
