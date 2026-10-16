"""Unit tests for Storage Governance Subsystem (Inspector, Compactor, SnapshotManager)."""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

import pytest

import myrm_agent_harness.observability.storage_governance.compactor as compactor_module
from myrm_agent_harness.observability.storage_governance import (
    StateSnapshotManager,
    StateStorageCompactor,
    StorageCategory,
    StorageGovernanceInspector,
)

_GIB = 1024**3


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


def _open_wal_database(db_path: Path) -> sqlite3.Connection:
    """A WAL database whose log is never checkpointed on its own, so a compaction has a log to truncate."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA wal_autocheckpoint=0")
    conn.execute("CREATE TABLE payloads (id INTEGER PRIMARY KEY, body BLOB)")
    conn.executemany("INSERT INTO payloads (body) VALUES (?)", [(os.urandom(2048),) for _ in range(40)])
    conn.commit()
    return conn


def _reserve_sparse(path: Path, size: int) -> None:
    """A file that reports `size` bytes without occupying them on disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        handle.truncate(size)


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
    assert sqlite_cat.details["chats"] == 50
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
    assert checkpoints.details == {"conversations.sqlite": 4096, "conversations.sqlite-wal": 1000}
    assert report.total_storage_bytes == 5096


def test_inspector_tolerates_a_checkpoint_database_that_does_not_exist_yet(tmp_path: Path):
    inspector = StorageGovernanceInspector(tmp_path / "myrm_data", checkpoints_db=tmp_path / "missing.db")

    checkpoints = next(c for c in inspector.inspect().categories if c.category is StorageCategory.CHECKPOINTS)

    assert (checkpoints.bytes, checkpoints.item_count, checkpoints.details) == (0, 0, {})


def test_large_checkpoint_database_counts_toward_growth_health(tmp_path: Path):
    data_dir = tmp_path / "myrm_data"
    checkpoint_db = data_dir / "checkpoints.db"
    _reserve_sparse(checkpoint_db, 3 * _GIB)

    unhealthy = StorageGovernanceInspector(data_dir, checkpoints_db=checkpoint_db).inspect()
    healthy = StorageGovernanceInspector(data_dir).inspect()

    assert unhealthy.total_storage_bytes == 3 * _GIB
    assert unhealthy.is_growth_healthy is False
    assert healthy.is_growth_healthy is True
    # Checkpoint history is reclaimed automatically; there is nothing for the user to act on.
    assert not any("heckpoint" in advice for advice in unhealthy.recommended_actions)


def test_inspector_advises_compaction_for_an_oversized_wal(tmp_path: Path):
    data_dir = tmp_path / "myrm_data"
    data_dir.mkdir()
    _reserve_sparse(data_dir / "data.db-wal", 60 * 1024 * 1024)

    report = StorageGovernanceInspector(data_dir).inspect()

    assert any("WAL" in advice for advice in report.recommended_actions)


def test_compactor_truncates_the_wal_and_measures_only_the_database_footprint(tmp_path: Path):
    data_dir = tmp_path / "myrm_data"
    data_dir.mkdir()
    db_file = data_dir / "data.db"
    wal_file = data_dir / "data.db-wal"
    _reserve_sparse(data_dir / "harness" / "bulk.bin", 8 * 1024 * 1024)
    writer = _open_wal_database(db_file)
    try:
        footprint_before = db_file.stat().st_size + wal_file.stat().st_size
        assert wal_file.stat().st_size > 0

        result = StateStorageCompactor(data_dir).compact()

        assert result.success is True
        assert result.wal_truncated is True
        assert wal_file.stat().st_size == 0
        assert result.initial_bytes == footprint_before
        assert result.final_bytes == db_file.stat().st_size
        assert result.freed_bytes == max(0, result.initial_bytes - result.final_bytes)
        assert result.duration_ms >= 0
    finally:
        writer.close()


def test_compactor_reports_a_wal_that_an_active_reader_kept_from_truncating(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(compactor_module, "_BUSY_TIMEOUT_SECONDS", 0.05)
    data_dir = tmp_path / "myrm_data"
    data_dir.mkdir()
    db_file = data_dir / "data.db"
    writer = _open_wal_database(db_file)
    reader = sqlite3.connect(str(db_file))
    try:
        reader.execute("BEGIN")
        reader.execute("SELECT COUNT(*) FROM payloads").fetchone()
        writer.execute("INSERT INTO payloads (body) VALUES (randomblob(2048))")
        writer.commit()

        result = StateStorageCompactor(data_dir).compact()

        assert result.success is True
        assert result.wal_truncated is False
        assert Path(f"{db_file}-wal").stat().st_size > 0
    finally:
        reader.close()
        writer.close()


def test_compactor_reclaims_free_pages_of_an_incremental_vacuum_database(tmp_path: Path):
    data_dir = tmp_path / "myrm_data"
    data_dir.mkdir()
    db_file = data_dir / "data.db"
    conn = sqlite3.connect(str(db_file))
    try:
        conn.execute("PRAGMA auto_vacuum=INCREMENTAL")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE payloads (id INTEGER PRIMARY KEY, body BLOB)")
        conn.executemany("INSERT INTO payloads (body) VALUES (?)", [(os.urandom(8000),) for _ in range(300)])
        conn.commit()
        conn.execute("DELETE FROM payloads")
        conn.commit()
        free_before = conn.execute("PRAGMA freelist_count").fetchone()[0]
        page_size = conn.execute("PRAGMA page_size").fetchone()[0]
    finally:
        conn.close()

    result = StateStorageCompactor(data_dir).compact(incremental_pages=100)

    reopened = sqlite3.connect(str(db_file))
    try:
        assert reopened.execute("PRAGMA freelist_count").fetchone()[0] == free_before - 100
    finally:
        reopened.close()
    assert result.freed_bytes == 100 * page_size


def test_compactor_never_deletes_workspace_files_named_like_temporary_files(tmp_path: Path):
    data_dir = tmp_path / "myrm_data"
    data_dir.mkdir()
    _init_sample_sqlite_db(data_dir / "data.db")
    month_ago = time.time() - 30 * 86400
    kept = [data_dir / "harness" / "workspaces" / "project" / name for name in ("orphan_notes.md", "draft.tmp")]
    for path in kept:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("the user's file")
        os.utime(path, (month_ago, month_ago))

    StateStorageCompactor(data_dir).compact()

    assert all(path.read_text() == "the user's file" for path in kept)


def test_compactor_reports_failure_without_exposing_the_database_error(tmp_path: Path):
    data_dir = tmp_path / "myrm_data"
    data_dir.mkdir()
    (data_dir / "data.db").write_bytes(b"this is not a database " * 200)

    result = StateStorageCompactor(data_dir).compact()

    assert result.success is False
    assert result.freed_bytes == 0
    assert "not a database" not in result.message


def test_compactor_has_nothing_to_do_without_a_database(tmp_path: Path):
    result = StateStorageCompactor(tmp_path / "myrm_data").compact()

    assert result.success is True
    assert (result.initial_bytes, result.final_bytes, result.freed_bytes) == (0, 0, 0)


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
