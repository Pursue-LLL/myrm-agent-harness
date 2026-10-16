# storage_governance/

## Overview
Subsystem for Agent persistent state storage governance: space inspection and snapshot-based disaster recovery/rollback. Space is reclaimed elsewhere: checkpoint history by `runtime/checkpointing/pruning.py`, backup images by `infra/sqlite_backup.py`.

The application declares where each category lives (`layout`: category → paths, wherever they are, including volumes outside the data directory); the inspector owns the rules: a file counts toward the category with the deepest declared path above it, the journals beside a declared database file (`-wal`, `-shm`, `-journal`) belong to it, and what no category claims of the data directory is `OTHER`, so the categories always add up to the whole data directory (plus any relocated paths). Symbolic links are not followed; only regular files count, by apparent size.

## File Index

| File | Role | Description |
|------|------|-------------|
| `__init__.py` | Package | Re-exports the inspector, snapshot management and the shared storage report types. |
| `types.py` | Core | Data models and contracts (`StorageCategory`, `StorageCategoryBreakdown`, `StorageGovernanceReport`, `StateSnapshotMetadata`). |
| `layout.py` | Core | `resolve_layout`: validates the declared layout and settles ownership (deepest path wins, database journals, `OTHER` remainder, clashes go to the first category in enum order and are logged). Pure path logic, no measuring. |
| `walker.py` | Core | `measure_tree`: apparent bytes and regular-file count of one tree with `os.scandir`, leaving out the paths other categories own. Unreadable entries count as empty. |
| `inspector.py` | Core | `StorageGovernanceInspector`: measures every category of the resolved layout and assembles the report with disk usage. |
| `snapshot_manager.py` | Core | `StateSnapshotManager` supporting point-in-time state checkpointing and atomic rollback. |
