"""Unit tests for Storage Governance Subsystem (Inspector, SnapshotManager)."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from contextlib import AbstractContextManager
from pathlib import Path

import pytest

from myrm_agent_harness.observability.storage_governance import (
    StateSnapshotManager,
    StorageCategory,
    StorageGovernanceInspector,
    StorageGovernanceReport,
)
from myrm_agent_harness.observability.storage_governance.walker import measure_tree


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


def _write(path: Path, size: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return path


def _apparent_size(directory: Path) -> int:
    """The size of a tree by an independent plain walk, to anchor the report against."""
    return sum(f.stat().st_size for f in directory.rglob("*") if f.is_file() and not f.is_symlink())


def _by_category(report: StorageGovernanceReport) -> dict[StorageCategory, tuple[int, int]]:
    return {c.category: (c.bytes, c.item_count) for c in report.categories}


def _server_layout(root: Path) -> dict[StorageCategory, tuple[Path, ...]]:
    """Where the server keeps each category inside its data directory."""
    return {
        StorageCategory.SQLITE_DATABASE: (root / "data.db",),
        StorageCategory.CHECKPOINTS: (root / "checkpoints.db",),
        StorageCategory.WORKSPACES: (root / "harness",),
        StorageCategory.VECTOR_STORE: (root / "qdrant",),
        StorageCategory.MEMORY_ARCHIVE: (root / "memory",),
        StorageCategory.EVENT_LOGS: (root / "event_logs",),
        StorageCategory.SQLITE_BACKUPS: (root / "sqlite_backups",),
        StorageCategory.SNAPSHOTS: (root / "snapshots",),
    }


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """A data directory with one file of a distinct size per category and one nobody claims."""
    root = tmp_path / "myrm_data"
    _write(root / "data.db", 1000)
    _write(root / "data.db-wal", 100)
    _write(root / "checkpoints.db", 2000)
    _write(root / "harness" / "workspaces" / "project" / "notes.md", 300)
    _write(root / "qdrant" / "meta.json", 40)
    _write(root / "memory" / "m.md", 5)
    _write(root / "event_logs" / "e.jsonl", 6)
    _write(root / "sqlite_backups" / "snapshots" / "b1.sqlite", 7000)
    _write(root / "sqlite_backups" / "snapshots" / "b2.sqlite", 7000)
    _write(root / "snapshots" / "snap_1" / "data.db", 8000)
    _write(root / "wiki" / "page.md", 9)
    return root


def test_every_byte_of_the_data_directory_lands_in_exactly_one_category(data_dir: Path) -> None:
    report = StorageGovernanceInspector(data_dir, layout=_server_layout(data_dir)).inspect()

    assert _by_category(report) == {
        StorageCategory.SQLITE_DATABASE: (1100, 2),
        StorageCategory.CHECKPOINTS: (2000, 1),
        StorageCategory.WORKSPACES: (300, 1),
        StorageCategory.VECTOR_STORE: (40, 1),
        StorageCategory.MEMORY_ARCHIVE: (5, 1),
        StorageCategory.EVENT_LOGS: (6, 1),
        StorageCategory.SQLITE_BACKUPS: (14000, 2),
        StorageCategory.SNAPSHOTS: (8000, 1),
        StorageCategory.OTHER: (9, 1),
    }
    assert report.total_storage_bytes == _apparent_size(data_dir)
    assert sum(c.percentage for c in report.categories) == pytest.approx(100, abs=0.5)
    assert report.disk_total_bytes > 0
    assert report.disk_free_bytes >= 0


def test_categories_are_reported_in_declaration_order_with_other_last(data_dir: Path) -> None:
    layout = _server_layout(data_dir)
    shuffled = dict(reversed(layout.items()))

    report = StorageGovernanceInspector(data_dir, layout=shuffled).inspect()

    assert [c.category for c in report.categories] == [*layout, StorageCategory.OTHER]


def test_only_declared_categories_are_reported_besides_other(data_dir: Path) -> None:
    layout = {StorageCategory.CHECKPOINTS: (data_dir / "checkpoints.db",)}

    report = StorageGovernanceInspector(data_dir, layout=layout).inspect()

    assert [c.category for c in report.categories] == [StorageCategory.CHECKPOINTS, StorageCategory.OTHER]
    assert report.total_storage_bytes == _apparent_size(data_dir)


def test_paths_outside_the_data_directory_are_measured_where_they_are(tmp_path: Path) -> None:
    data_dir = tmp_path / "myrm_data"
    nas = tmp_path / "nas"
    _write(data_dir / "data.db", 1000)
    _write(data_dir / "wiki" / "page.md", 9)
    _write(nas / "memory" / "m.md", 50)
    _write(nas / "logs" / "e.jsonl", 60)
    layout = {
        StorageCategory.SQLITE_DATABASE: (data_dir / "data.db",),
        StorageCategory.MEMORY_ARCHIVE: (nas / "memory",),
        StorageCategory.EVENT_LOGS: (nas / "logs",),
    }

    report = StorageGovernanceInspector(data_dir, layout=layout).inspect()

    assert _by_category(report) == {
        StorageCategory.SQLITE_DATABASE: (1000, 1),
        StorageCategory.MEMORY_ARCHIVE: (50, 1),
        StorageCategory.EVENT_LOGS: (60, 1),
        StorageCategory.OTHER: (9, 1),
    }
    assert report.total_storage_bytes == _apparent_size(data_dir) + _apparent_size(nas)


def test_the_deepest_declared_path_owns_a_nested_subtree(tmp_path: Path) -> None:
    data_dir = tmp_path / "myrm_data"
    _write(data_dir / "harness" / "workspace" / "a.md", 300)
    _write(data_dir / "harness" / ".memories" / "m.md", 70)
    layout = {
        StorageCategory.WORKSPACES: (data_dir / "harness",),
        StorageCategory.MEMORY_ARCHIVE: (data_dir / "harness" / ".memories",),
    }

    report = StorageGovernanceInspector(data_dir, layout=layout).inspect()

    assert _by_category(report)[StorageCategory.WORKSPACES] == (300, 1)
    assert _by_category(report)[StorageCategory.MEMORY_ARCHIVE] == (70, 1)
    assert report.total_storage_bytes == _apparent_size(data_dir)


def test_journals_follow_their_database_but_lookalike_files_do_not(tmp_path: Path) -> None:
    data_dir = tmp_path / "myrm_data"
    for suffix, size in (("", 1000), ("-wal", 100), ("-shm", 10), ("-journal", 1)):
        _write(data_dir / f"data.db{suffix}", size)
    _write(data_dir / "data.db.optimize_backup", 500)
    layout = {StorageCategory.SQLITE_DATABASE: (data_dir / "data.db",)}

    report = StorageGovernanceInspector(data_dir, layout=layout).inspect()

    assert _by_category(report) == {
        StorageCategory.SQLITE_DATABASE: (1111, 4),
        StorageCategory.OTHER: (500, 1),
    }


def test_a_live_database_is_attributed_together_with_its_write_ahead_log(tmp_path: Path) -> None:
    data_dir = tmp_path / "myrm_data"
    data_dir.mkdir()
    db_file = data_dir / "data.db"
    conn = sqlite3.connect(str(db_file))
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA wal_autocheckpoint=0;")
        conn.execute("CREATE TABLE t (x TEXT);")
        conn.execute("INSERT INTO t VALUES (?)", ("x" * 5000,))
        conn.commit()
        on_disk = [db_file, data_dir / "data.db-wal", data_dir / "data.db-shm"]
        assert all(path.exists() for path in on_disk), "the sidecars under test must really exist"
        expected = sum(path.stat().st_size for path in on_disk)

        report = StorageGovernanceInspector(data_dir, layout={StorageCategory.SQLITE_DATABASE: (db_file,)}).inspect()
    finally:
        conn.close()

    assert _by_category(report) == {
        StorageCategory.SQLITE_DATABASE: (expected, 3),
        StorageCategory.OTHER: (0, 0),
    }


def test_other_is_reported_even_when_nothing_is_left_over(tmp_path: Path) -> None:
    data_dir = tmp_path / "myrm_data"
    _write(data_dir / "data.db", 10)

    report = StorageGovernanceInspector(
        data_dir, layout={StorageCategory.SQLITE_DATABASE: (data_dir / "data.db",)}
    ).inspect()

    assert _by_category(report)[StorageCategory.OTHER] == (0, 0)


def test_a_category_that_owns_the_whole_data_directory_leaves_nothing_for_other(tmp_path: Path) -> None:
    data_dir = tmp_path / "myrm_data"
    _write(data_dir / "a.bin", 10)
    _write(data_dir / "sub" / "b.bin", 20)

    report = StorageGovernanceInspector(data_dir, layout={StorageCategory.MEMORY_ARCHIVE: (data_dir,)}).inspect()

    assert _by_category(report) == {StorageCategory.MEMORY_ARCHIVE: (30, 2), StorageCategory.OTHER: (0, 0)}


def test_inspecting_a_data_directory_that_does_not_exist_yet_creates_nothing(tmp_path: Path) -> None:
    data_dir = tmp_path / "not" / "yet"
    layout = {StorageCategory.CHECKPOINTS: (tmp_path / "missing.db",)}

    report = StorageGovernanceInspector(data_dir, layout=layout).inspect()

    assert not (tmp_path / "not").exists()
    assert report.total_storage_bytes == 0
    assert report.disk_total_bytes > 0
    assert [(c.bytes, c.item_count) for c in report.categories] == [(0, 0), (0, 0)]


def test_links_inside_a_category_are_not_followed(tmp_path: Path) -> None:
    data_dir = tmp_path / "myrm_data"
    outside = tmp_path / "outside"
    _write(data_dir / "memory" / "m.md", 5)
    _write(outside / "big.bin", 5000)
    try:
        os.symlink(outside, data_dir / "memory" / "dir_link", target_is_directory=True)
        os.symlink(outside / "big.bin", data_dir / "memory" / "file_link")
    except OSError:
        pytest.skip("symbolic links are not available")

    report = StorageGovernanceInspector(
        data_dir, layout={StorageCategory.MEMORY_ARCHIVE: (data_dir / "memory",)}
    ).inspect()

    assert _by_category(report) == {StorageCategory.MEMORY_ARCHIVE: (5, 1), StorageCategory.OTHER: (0, 0)}


def test_a_declared_root_that_is_a_link_is_followed_once(tmp_path: Path) -> None:
    data_dir = tmp_path / "myrm_data"
    relocated = tmp_path / "volume" / "qdrant"
    _write(relocated / "meta.json", 40)
    data_dir.mkdir()
    try:
        os.symlink(relocated, data_dir / "qdrant", target_is_directory=True)
    except OSError:
        pytest.skip("symbolic links are not available")

    report = StorageGovernanceInspector(
        data_dir, layout={StorageCategory.VECTOR_STORE: (data_dir / "qdrant",)}
    ).inspect()

    assert _by_category(report) == {StorageCategory.VECTOR_STORE: (40, 1), StorageCategory.OTHER: (0, 0)}


def test_an_unreadable_directory_counts_as_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "tree"
    _write(root / "readable" / "a.bin", 10)
    _write(root / "locked" / "b.bin", 20)
    real_scandir = os.scandir

    def scandir(path: str | os.PathLike[str]) -> AbstractContextManager[Iterator[os.DirEntry[str]]]:
        if os.fspath(path).endswith("locked"):
            raise PermissionError(path)
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", scandir)

    assert measure_tree(str(root)) == (10, 1)


def test_measure_tree_leaves_skipped_paths_to_their_owner(tmp_path: Path) -> None:
    root = tmp_path / "tree"
    _write(root / "a.bin", 10)
    _write(root / "owned" / "b.bin", 20)
    _write(root / "owned" / "deeper" / "c.bin", 30)

    assert measure_tree(str(root), frozenset({os.path.normcase(root / "owned")})) == (10, 1)


def test_measure_tree_accepts_a_single_file_and_a_missing_path(tmp_path: Path) -> None:
    file = _write(tmp_path / "one.db", 123)

    assert measure_tree(str(file)) == (123, 1)
    assert measure_tree(str(tmp_path / "missing")) == (0, 0)


def test_snapshot_manager_lifecycle(tmp_path: Path) -> None:
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
