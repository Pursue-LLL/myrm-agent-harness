"""Tests for LocalFileSnapshotStore — file-copy fallback implementation.

Covers: take_snapshot, restore, diff, list_snapshots, delete_snapshot,
        cleanup, DEFAULT_EXCLUDES behavior, large file skipping,
        pre-rollback on restore, _default_local_snapshot_path.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from myrm_agent_harness.agent.file_snapshot.local_store import (
    LocalFileSnapshotStore,
    _default_local_snapshot_path,
)
from myrm_agent_harness.agent.file_snapshot.types import SnapshotTrigger


@pytest.fixture
def store(tmp_path: Path) -> LocalFileSnapshotStore:
    return LocalFileSnapshotStore(storage_path=tmp_path / "local_snapshots")


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "main.py").write_text("print('main')\n")
    (ws / "docs").mkdir()
    (ws / "docs" / "readme.txt").write_text("readme content\n")
    return ws


# ------------------------------------------------------------------
# _default_local_snapshot_path
# ------------------------------------------------------------------


def test_default_path_uses_myrm_data_dir():
    with patch.dict("os.environ", {"MYRM_DATA_DIR": "/data/myrm"}, clear=False):
        p = _default_local_snapshot_path()
    assert p == Path("/data/myrm/file_snapshots/local")


def test_default_path_fallback():
    with patch.dict("os.environ", {}, clear=True):
        p = _default_local_snapshot_path()
    assert p == Path.home() / ".myrm" / "file_snapshots" / "local"


# ------------------------------------------------------------------
# take_snapshot
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_take_snapshot_creates_manifest(store: LocalFileSnapshotStore, workspace: Path):
    sid = await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "test")
    assert sid.startswith("fs_")

    snap_dir = store._find_snapshot_dir(sid)
    assert snap_dir is not None
    manifest = json.loads((snap_dir / "manifest.json").read_text())
    assert manifest["trigger"] == "manual"
    assert manifest["file_count"] == 2


@pytest.mark.asyncio
async def test_take_snapshot_copies_files(store: LocalFileSnapshotStore, workspace: Path):
    sid = await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "test")
    snap_dir = store._find_snapshot_dir(sid)
    assert (snap_dir / "files" / "main.py").read_text() == "print('main')\n"
    assert (snap_dir / "files" / "docs" / "readme.txt").read_text() == "readme content\n"


@pytest.mark.asyncio
async def test_take_snapshot_excludes_node_modules(store: LocalFileSnapshotStore, workspace: Path):
    nm = workspace / "node_modules"
    nm.mkdir()
    (nm / "pkg.js").write_text("module\n")

    sid = await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "test")
    snap_dir = store._find_snapshot_dir(sid)
    assert not (snap_dir / "files" / "node_modules").exists()


@pytest.mark.asyncio
async def test_take_snapshot_skips_large_file(store: LocalFileSnapshotStore, workspace: Path):
    large = workspace / "huge.bin"
    large.write_bytes(b"\x00" * (11 * 1024 * 1024))  # 11 MB

    sid = await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "test")
    manifest = json.loads((store._find_snapshot_dir(sid) / "manifest.json").read_text())
    assert manifest["file_count"] == 2  # main.py + readme.txt, not huge.bin


# ------------------------------------------------------------------
# list_snapshots
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_snapshots(store: LocalFileSnapshotStore, workspace: Path):
    sid1 = await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "first")
    sid2 = await store.take_snapshot(str(workspace), SnapshotTrigger.WRITE_FILE, "second")

    snaps = await store.list_snapshots(str(workspace))
    assert len(snaps) == 2
    assert snaps[0].snapshot_id == sid2  # newest first


@pytest.mark.asyncio
async def test_list_snapshots_empty(store: LocalFileSnapshotStore, tmp_path: Path):
    ws = tmp_path / "empty"
    ws.mkdir()
    snaps = await store.list_snapshots(str(ws))
    assert snaps == []


# ------------------------------------------------------------------
# restore
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_restore_full(store: LocalFileSnapshotStore, workspace: Path):
    sid = await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "baseline")
    (workspace / "main.py").write_text("modified\n")

    result = await store.restore(sid)
    assert result.success is True
    assert (workspace / "main.py").read_text() == "print('main')\n"


@pytest.mark.asyncio
async def test_restore_creates_pre_rollback(store: LocalFileSnapshotStore, workspace: Path):
    sid = await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "baseline")
    (workspace / "main.py").write_text("changed\n")

    result = await store.restore(sid)
    assert result.pre_rollback_snapshot_id is not None


@pytest.mark.asyncio
async def test_restore_specific_files(store: LocalFileSnapshotStore, workspace: Path):
    sid = await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "baseline")
    (workspace / "main.py").write_text("modified\n")
    (workspace / "docs" / "readme.txt").write_text("also modified\n")

    result = await store.restore(sid, files=["main.py"])
    assert result.success is True
    assert result.files_restored == 1
    assert (workspace / "main.py").read_text() == "print('main')\n"
    assert (workspace / "docs" / "readme.txt").read_text() == "also modified\n"


@pytest.mark.asyncio
async def test_restore_not_found(store: LocalFileSnapshotStore):
    result = await store.restore("nonexistent_id")
    assert result.success is False


# ------------------------------------------------------------------
# diff
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_diff_detects_modification(store: LocalFileSnapshotStore, workspace: Path):
    sid = await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "baseline")
    (workspace / "main.py").write_text("changed\n")

    diff = await store.diff(sid)
    assert diff.total_changes > 0
    changed = [c for c in diff.changes if c.path == "main.py"]
    assert len(changed) == 1
    assert changed[0].change_type == "modified"


@pytest.mark.asyncio
async def test_diff_detects_new_file(store: LocalFileSnapshotStore, workspace: Path):
    sid = await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "baseline")
    (workspace / "new.txt").write_text("new\n")

    diff = await store.diff(sid)
    added = [c for c in diff.changes if c.change_type == "added"]
    assert any(c.path == "new.txt" for c in added)


@pytest.mark.asyncio
async def test_diff_detects_deleted_file(store: LocalFileSnapshotStore, workspace: Path):
    sid = await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "baseline")
    (workspace / "main.py").unlink()

    diff = await store.diff(sid)
    deleted = [c for c in diff.changes if c.change_type == "deleted"]
    assert any(c.path == "main.py" for c in deleted)


# ------------------------------------------------------------------
# delete_snapshot
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_snapshot(store: LocalFileSnapshotStore, workspace: Path):
    sid = await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "test")
    assert await store.delete_snapshot(sid) is True
    assert await store.delete_snapshot(sid) is False


# ------------------------------------------------------------------
# cleanup
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cleanup_removes_old(store: LocalFileSnapshotStore, workspace: Path):
    for i in range(5):
        await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, f"iter-{i}")

    snaps_before = await store.list_snapshots(str(workspace), limit=100)
    assert len(snaps_before) == 5

    deleted = await store.cleanup(str(workspace), max_snapshots=2)
    assert deleted == 3

    snaps_after = await store.list_snapshots(str(workspace), limit=100)
    assert len(snaps_after) == 2
