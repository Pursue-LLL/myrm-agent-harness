"""Unit tests for Storage Governance Subsystem (Inspector, SnapshotManager)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from myrm_agent_harness.observability.storage_governance import (
    StateSnapshotManager,
    StorageCategory,
    StorageGovernanceInspector,
)


def _init_sample_sqlite_db(db_path: Path) -> None:
    """Initialize a sample SQLite DB with tables and records."""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("CREATE TABLE chats (id TEXT PRIMARY KEY, title TEXT);")
        conn.execute("CREATE TABLE messages (id TEXT PRIMARY KEY, content TEXT);")
        for i in range(50):
            conn.execute(f"INSERT INTO chats VALUES ('chat_{i}', 'Chat Title {i}');")
            conn.execute(f"INSERT INTO messages VALUES ('msg_{i}', 'Message payload body {i}');")
        conn.commit()
    finally:
        conn.close()


def test_inspector_attributes_each_data_directory_entry_to_its_own_category(tmp_path: Path):
    data_dir = tmp_path / "myrm_data"
    data_dir.mkdir()
    _init_sample_sqlite_db(data_dir / "data.db")
    (data_dir / "qdrant").mkdir()
    (data_dir / "qdrant" / "meta.json").write_text('{"collection": "memories"}')
    workspace_file = data_dir / "harness" / "workspaces" / "project" / "notes.md"
    workspace_file.parent.mkdir(parents=True)
    workspace_file.write_text("workspace file")

    report = StorageGovernanceInspector(data_dir).inspect()

    assert report.disk_total_bytes > 0
    assert report.disk_free_bytes >= 0
    categories = {c.category: c for c in report.categories}
    assert set(categories) == {
        StorageCategory.SQLITE_DATABASE,
        StorageCategory.CHECKPOINTS,
        StorageCategory.WORKSPACES,
        StorageCategory.VECTOR_STORE,
        StorageCategory.MEMORY_ARCHIVE,
        StorageCategory.EVENT_LOGS,
        StorageCategory.SNAPSHOTS,
    }
    sqlite_cat = categories[StorageCategory.SQLITE_DATABASE]
    assert sqlite_cat.bytes > 0
    assert sqlite_cat.item_count >= 1
    assert categories[StorageCategory.WORKSPACES].bytes == len("workspace file")
    assert categories[StorageCategory.WORKSPACES].item_count == 1
    assert categories[StorageCategory.VECTOR_STORE].item_count == 1
    assert categories[StorageCategory.CHECKPOINTS].bytes == 0
    assert report.total_storage_bytes == sum(c.bytes for c in report.categories)
    assert sum(c.percentage for c in report.categories) == pytest.approx(100, abs=0.5)


def test_inspector_attributes_the_checkpoint_database_wherever_it_lives(tmp_path: Path):
    data_dir = tmp_path / "myrm_data"
    checkpoint_db = tmp_path / "elsewhere" / "conversations.sqlite"
    checkpoint_db.parent.mkdir()
    checkpoint_db.write_bytes(b"\0" * 4096)
    checkpoint_db.with_name("conversations.sqlite-wal").write_bytes(b"\0" * 1000)

    report = StorageGovernanceInspector(data_dir, checkpoints_db=checkpoint_db).inspect()

    checkpoints = next(c for c in report.categories if c.category is StorageCategory.CHECKPOINTS)
    assert checkpoints.bytes == 5096
    assert checkpoints.item_count == 2
    assert report.total_storage_bytes == 5096


def test_inspector_tolerates_a_checkpoint_database_that_does_not_exist_yet(tmp_path: Path):
    inspector = StorageGovernanceInspector(tmp_path / "myrm_data", checkpoints_db=tmp_path / "missing.db")

    checkpoints = next(c for c in inspector.inspect().categories if c.category is StorageCategory.CHECKPOINTS)

    assert (checkpoints.bytes, checkpoints.item_count) == (0, 0)


def test_snapshot_manager_lifecycle(tmp_path: Path):
    """Test creating, listing, restoring, and deleting point-in-time snapshots."""
    data_dir = tmp_path / "myrm_data"
    data_dir.mkdir(parents=True, exist_ok=True)

    db_file = data_dir / "data.db"
    _init_sample_sqlite_db(db_file)

    mgr = StateSnapshotManager(data_dir)

    # 1. Create snapshot
    meta = mgr.create_snapshot(label="Pre-Upgrade Backup")
    assert meta.snapshot_id.startswith("snap_")
    assert meta.label == "Pre-Upgrade Backup"
    assert meta.size_bytes > 0
    assert len(meta.checksum) == 64

    # 2. List snapshots
    snapshots = mgr.list_snapshots()
    assert len(snapshots) == 1
    assert snapshots[0].snapshot_id == meta.snapshot_id

    # 3. Modify current DB to simulate corrupted upgrade
    conn = sqlite3.connect(str(db_file))
    conn.execute("DELETE FROM chats;")
    conn.commit()
    conn.close()

    # Verify rows deleted
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM chats;")
    assert cur.fetchone()[0] == 0
    conn.close()

    # 4. Restore snapshot
    restore_ok = mgr.restore_snapshot(meta.snapshot_id)
    assert restore_ok is True

    # Verify rows restored
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM chats;")
    assert cur.fetchone()[0] == 50
    conn.close()

    # 5. Delete snapshot
    del_ok = mgr.delete_snapshot(meta.snapshot_id)
    assert del_ok is True
    assert len(mgr.list_snapshots()) == 0

    # 6. Restore non-existent snapshot
    assert mgr.restore_snapshot("non_existent_snap") is False
