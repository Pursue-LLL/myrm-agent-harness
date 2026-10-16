# storage_governance/

## Overview
Subsystem for Agent persistent state storage governance: space inspection and snapshot-based disaster recovery/rollback. Space is reclaimed elsewhere: checkpoint history by `runtime/checkpointing/pruning.py`, backup images by `infra/sqlite_backup.py`.

## File Index

| File | Role | Description |
|------|------|-------------|
| `__init__.py` | Package | Re-exports the inspector, snapshot management and the shared storage report types. |
| `types.py` | Core | Data models and contracts (`StorageCategory`, `StorageCategoryBreakdown`, `StorageGovernanceReport`, `StateSnapshotMetadata`). |
| `inspector.py` | Core | `StorageGovernanceInspector` for per-category space attribution (file sizes only). The checkpoint database lives wherever the application configures it, so it is attributed through the explicit `checkpoints_db` path. |
| `snapshot_manager.py` | Core | `StateSnapshotManager` supporting point-in-time state checkpointing and atomic rollback. |
