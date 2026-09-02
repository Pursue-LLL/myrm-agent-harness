"""Unit tests for Storage Governance Subsystem (Inspector, Compactor, SnapshotManager)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from myrm_agent_harness.observability.storage_governance import (
    StateSnapshotManager,
    StateStorageCompactor,
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
            conn.execute(
                f"INSERT INTO messages VALUES ('msg_{i}', 'Message payload body {i}');"
            )
        conn.commit()
    finally:
        conn.close()


def test_storage_governance_inspector(tmp_path: Path):
    """Test storage governance inspector calculating breakdown across categories."""
    data_dir = tmp_path / "myrm_data"
    data_dir.mkdir(parents=True, exist_ok=True)

    # 1. Create SQLite DB
    db_file = data_dir / "data.db"
    _init_sample_sqlite_db(db_file)

    # 2. Create Vector Storage (Qdrant mock)
    qdrant_dir = data_dir / "qdrant"
    qdrant_dir.mkdir(parents=True, exist_ok=True)
    (qdrant_dir / "meta.json").write_text('{"collection": "memories"}')

    # 3. Create Checkpoint files under harness
    harness_dir = data_dir / "harness"
    harness_dir.mkdir(parents=True, exist_ok=True)
    (harness_dir / "chk_1.json").write_text('{"state": "running"}')
    (harness_dir / "orphan_1.tmp").write_text("temporary-checkpoint-bytes")

    inspector = StorageGovernanceInspector(data_dir)
    report = inspector.inspect()

    assert report.total_storage_bytes > 0
    assert report.disk_total_bytes > 0
    assert report.disk_free_bytes >= 0
    assert len(report.categories) > 0

    # Category checks
    categories_map = {c.category: c for c in report.categories}
    assert StorageCategory.SQLITE_DATABASE in categories_map
    sqlite_cat = categories_map[StorageCategory.SQLITE_DATABASE]
    assert sqlite_cat.bytes > 0
    assert "chats" in sqlite_cat.details
    assert sqlite_cat.details["chats"] == 50

    assert StorageCategory.CHECKPOINTS in categories_map
    assert StorageCategory.VECTOR_STORE in categories_map


def test_storage_compactor(tmp_path: Path):
    """Test state storage compactor executing WAL truncation and orphan purging."""
    data_dir = tmp_path / "myrm_data"
    data_dir.mkdir(parents=True, exist_ok=True)

    db_file = data_dir / "data.db"
    _init_sample_sqlite_db(db_file)

    # Create orphan temporary files
    harness_dir = data_dir / "harness"
    harness_dir.mkdir(parents=True, exist_ok=True)
    orphan_tmp = harness_dir / "orphan_old.tmp"
    orphan_tmp.write_text("x" * 1024)

    compactor = StateStorageCompactor(data_dir)
    result = compactor.compact(
        purge_orphan_checkpoints=True,
        incremental_pages=100,
        max_orphan_age_seconds=0,  # force purge immediately
    )

    assert result.success is True
    assert result.wal_truncated is True
    assert result.purged_checkpoints >= 1
    assert result.duration_ms >= 0
    assert not orphan_tmp.exists()


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
