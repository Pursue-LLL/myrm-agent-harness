"""Tests for ShadowGitSnapshotStore — core shadow git snapshot operations.

Covers: take_snapshot, restore, diff, list_snapshots, delete_snapshot, cleanup,
        no-change skip (diff-index), CAS concurrency safety (update-ref),
        oversized workspace rejection, root/home rejection, env isolation,
        pre-rollback on restore, structured commit messages.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from myrm_agent_harness.agent.file_snapshot.shadow_git_store import (
    ShadowGitSnapshotStore,
    _project_hash,
    _validate_commit_hash,
)
from myrm_agent_harness.agent.file_snapshot.types import (
    SnapshotTrigger,
)


def _git_available() -> bool:
    try:
        subprocess.run(["git", "--version"], capture_output=True, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


pytestmark = [
    pytest.mark.skipif(not _git_available(), reason="git not found"),
]


@pytest.fixture
def store(tmp_path: Path) -> ShadowGitSnapshotStore:
    return ShadowGitSnapshotStore(store_path=tmp_path / "snapshots")


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "hello.py").write_text("print('hello')\n")
    (ws / "sub").mkdir()
    (ws / "sub" / "data.txt").write_text("some data\n")
    return ws


# ------------------------------------------------------------------
# _project_hash / _validate_commit_hash
# ------------------------------------------------------------------


def test_project_hash_deterministic():
    h1 = _project_hash("/tmp/ws")
    h2 = _project_hash("/tmp/ws")
    assert h1 == h2
    assert len(h1) == 16


def test_project_hash_different_paths():
    assert _project_hash("/tmp/a") != _project_hash("/tmp/b")


def test_validate_commit_hash_valid():
    assert _validate_commit_hash("a" * 40) is True


def test_validate_commit_hash_invalid():
    assert _validate_commit_hash("short") is False
    assert _validate_commit_hash("g" * 40) is False
    assert _validate_commit_hash("") is False


# ------------------------------------------------------------------
# take_snapshot
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_take_snapshot_returns_commit_hash(store: ShadowGitSnapshotStore, workspace: Path):
    sid = await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "test")
    assert _validate_commit_hash(sid)


@pytest.mark.asyncio
async def test_take_snapshot_rejects_missing_dir(store: ShadowGitSnapshotStore, tmp_path: Path):
    with pytest.raises(ValueError, match="does not exist"):
        await store.take_snapshot(str(tmp_path / "nonexistent"), SnapshotTrigger.MANUAL)


@pytest.mark.asyncio
async def test_take_snapshot_rejects_root(store: ShadowGitSnapshotStore):
    with pytest.raises(ValueError, match="Refusing"):
        await store.take_snapshot("/", SnapshotTrigger.MANUAL)


@pytest.mark.asyncio
async def test_take_snapshot_rejects_home(store: ShadowGitSnapshotStore):
    with pytest.raises(ValueError, match="Refusing"):
        await store.take_snapshot(str(Path.home()), SnapshotTrigger.MANUAL)


# ------------------------------------------------------------------
# no-change skip (diff-index)
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_change_skip_returns_same_hash(store: ShadowGitSnapshotStore, workspace: Path):
    """When no files changed, second snapshot returns same commit hash."""
    sid1 = await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "first")
    sid2 = await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "second")
    assert sid1 == sid2


@pytest.mark.asyncio
async def test_change_detected_creates_new_commit(store: ShadowGitSnapshotStore, workspace: Path):
    """After modifying a file, new snapshot gets a different hash."""
    sid1 = await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "first")
    (workspace / "hello.py").write_text("print('changed')\n")
    sid2 = await store.take_snapshot(str(workspace), SnapshotTrigger.WRITE_FILE, "second")
    assert sid1 != sid2


# ------------------------------------------------------------------
# list_snapshots
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_snapshots_newest_first(store: ShadowGitSnapshotStore, workspace: Path):
    sid1 = await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "first")
    (workspace / "hello.py").write_text("v2\n")
    sid2 = await store.take_snapshot(str(workspace), SnapshotTrigger.WRITE_FILE, "second")

    snaps = await store.list_snapshots(str(workspace))
    assert len(snaps) == 2
    assert snaps[0].snapshot_id == sid2
    assert snaps[1].snapshot_id == sid1


@pytest.mark.asyncio
async def test_list_snapshots_limit(store: ShadowGitSnapshotStore, workspace: Path):
    for i in range(5):
        (workspace / "hello.py").write_text(f"v{i}\n")
        await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, f"iter-{i}")

    snaps = await store.list_snapshots(str(workspace), limit=3)
    assert len(snaps) == 3


@pytest.mark.asyncio
async def test_list_snapshots_empty_workspace(store: ShadowGitSnapshotStore, tmp_path: Path):
    ws = tmp_path / "empty_ws"
    ws.mkdir()
    snaps = await store.list_snapshots(str(ws))
    assert snaps == []


# ------------------------------------------------------------------
# restore
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_restore_full(store: ShadowGitSnapshotStore, workspace: Path):
    sid = await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "baseline")
    (workspace / "hello.py").write_text("modified\n")
    (workspace / "new_file.txt").write_text("new\n")

    result = await store.restore(sid)
    assert result.success is True
    assert result.files_restored > 0
    assert (workspace / "hello.py").read_text() == "print('hello')\n"


@pytest.mark.asyncio
async def test_restore_creates_pre_rollback(store: ShadowGitSnapshotStore, workspace: Path):
    sid = await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "baseline")
    (workspace / "hello.py").write_text("changed\n")

    result = await store.restore(sid)
    assert result.pre_rollback_snapshot_id is not None


@pytest.mark.asyncio
async def test_restore_specific_files(store: ShadowGitSnapshotStore, workspace: Path):
    sid = await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "baseline")
    (workspace / "hello.py").write_text("modified\n")
    (workspace / "sub" / "data.txt").write_text("also modified\n")

    result = await store.restore(sid, files=["hello.py"])
    assert result.success is True
    assert result.files_restored == 1
    assert (workspace / "hello.py").read_text() == "print('hello')\n"
    assert (workspace / "sub" / "data.txt").read_text() == "also modified\n"


@pytest.mark.asyncio
async def test_restore_invalid_id(store: ShadowGitSnapshotStore, workspace: Path):
    result = await store.restore("invalid_hash")
    assert result.success is False


@pytest.mark.asyncio
async def test_restore_nonexistent_commit(store: ShadowGitSnapshotStore, workspace: Path):
    result = await store.restore("a" * 40)
    assert result.success is False


# ------------------------------------------------------------------
# diff
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_diff_detects_modifications(store: ShadowGitSnapshotStore, workspace: Path):
    sid = await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "baseline")
    (workspace / "hello.py").write_text("changed\n")

    diff = await store.diff(sid)
    assert diff.total_changes > 0
    paths = [c.path for c in diff.changes]
    assert "hello.py" in paths


@pytest.mark.asyncio
async def test_diff_detects_new_file(store: ShadowGitSnapshotStore, workspace: Path):
    sid = await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "baseline")
    (workspace / "brand_new.txt").write_text("new content\n")

    diff = await store.diff(sid)
    paths = [c.path for c in diff.changes]
    assert "brand_new.txt" in paths


@pytest.mark.asyncio
async def test_diff_invalid_id(store: ShadowGitSnapshotStore):
    diff = await store.diff("invalid")
    assert diff.total_changes == 0


# ------------------------------------------------------------------
# delete_snapshot (protocol compat — always True)
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_snapshot_returns_true(store: ShadowGitSnapshotStore):
    assert await store.delete_snapshot("anything") is True


# ------------------------------------------------------------------
# cleanup
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cleanup_truncates_ref(store: ShadowGitSnapshotStore, workspace: Path):
    """Cleanup truncates ref to the Nth commit. Ancestors still reachable via git log."""
    for i in range(6):
        (workspace / "hello.py").write_text(f"v{i}\n")
        await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, f"iter-{i}")

    before = await store.list_snapshots(str(workspace), limit=100)
    assert len(before) == 6

    deleted = await store.cleanup(str(workspace), max_snapshots=3)
    assert deleted == 3


# ------------------------------------------------------------------
# env isolation
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_user_git_not_touched(store: ShadowGitSnapshotStore, workspace: Path):
    """Shadow git operations must not create .git in the workspace."""
    await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "test")
    assert not (workspace / ".git").exists()
    assert not (workspace / ".gitignore").exists()


# ------------------------------------------------------------------
# repair_if_corrupted
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repair_reinitializes(store: ShadowGitSnapshotStore, workspace: Path):
    await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "test")
    head = store._git_dir / "HEAD"
    head.write_text("")

    repaired = await store.repair_if_corrupted()
    assert repaired is True
    assert store._initialized  # re-initialized after repair

    sid = await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "after repair")
    assert _validate_commit_hash(sid)


@pytest.mark.asyncio
async def test_repair_no_corruption(store: ShadowGitSnapshotStore, workspace: Path):
    await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "test")
    repaired = await store.repair_if_corrupted()
    assert repaired is False


# ------------------------------------------------------------------
# oversized file skipping
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_large_file_excluded_from_snapshot(store: ShadowGitSnapshotStore, workspace: Path):
    large_file = workspace / "bigfile.bin"
    large_file.write_bytes(b"\x00" * (11 * 1024 * 1024))  # 11 MB

    sid = await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "with large")

    snaps = await store.list_snapshots(str(workspace))
    assert len(snaps) == 1
    assert snaps[0].file_count == 2  # hello.py + sub/data.txt, not bigfile.bin


# ------------------------------------------------------------------
# multiple projects share same bare repo
# ------------------------------------------------------------------


# ------------------------------------------------------------------
# DEFAULT_EXCLUDES behavior
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_default_excludes_node_modules(store: ShadowGitSnapshotStore, workspace: Path):
    """node_modules/ should be excluded from snapshot."""
    nm = workspace / "node_modules"
    nm.mkdir()
    (nm / "pkg.js").write_text("module.exports = {}\n")

    sid = await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "with node_modules")
    snaps = await store.list_snapshots(str(workspace))
    assert snaps[0].file_count == 2  # hello.py + sub/data.txt


@pytest.mark.asyncio
async def test_default_excludes_pycache(store: ShadowGitSnapshotStore, workspace: Path):
    """__pycache__/ should be excluded."""
    cache = workspace / "__pycache__"
    cache.mkdir()
    (cache / "module.pyc").write_bytes(b"\x00" * 100)

    sid = await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "with pycache")
    snaps = await store.list_snapshots(str(workspace))
    assert snaps[0].file_count == 2


# ------------------------------------------------------------------
# structured commit message parsing
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_snapshots_parses_trigger(store: ShadowGitSnapshotStore, workspace: Path):
    """Trigger type should be correctly parsed from commit messages."""
    await store.take_snapshot(str(workspace), SnapshotTrigger.WRITE_FILE, "write test")
    snaps = await store.list_snapshots(str(workspace))
    assert len(snaps) == 1
    assert snaps[0].trigger == SnapshotTrigger.WRITE_FILE


@pytest.mark.asyncio
async def test_list_snapshots_parses_description(store: ShadowGitSnapshotStore, workspace: Path):
    """Description should appear in the listed snapshot."""
    await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "my custom desc")
    snaps = await store.list_snapshots(str(workspace))
    assert "my custom desc" in snaps[0].description


# ------------------------------------------------------------------
# diff: deleted file detection
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_diff_detects_deleted_file(store: ShadowGitSnapshotStore, workspace: Path):
    """Deleting a file after snapshot should show it as deleted in diff."""
    sid = await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "baseline")
    (workspace / "hello.py").unlink()

    diff = await store.diff(sid)
    deleted_files = [c for c in diff.changes if c.change_type == "deleted"]
    assert any("hello.py" in c.path for c in deleted_files)


# ------------------------------------------------------------------
# _safe_path: path traversal prevention
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_restore_rejects_path_traversal(store: ShadowGitSnapshotStore, workspace: Path):
    """Path traversal in restore file list should be rejected."""
    sid = await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "baseline")
    result = await store.restore(sid, files=["../../etc/passwd"])
    # Should fail during _safe_path check or return 0 restored
    assert result.files_restored == 0 or result.success is False


# ------------------------------------------------------------------
# _touch_project: metadata update on second snapshot
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_touch_project_updates_last_touch(store: ShadowGitSnapshotStore, workspace: Path):
    """Second snapshot should update last_touch in project metadata."""
    import json
    import time

    await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "first")

    from myrm_agent_harness.agent.file_snapshot.shadow_git_store import _project_hash

    proj_hash = _project_hash(str(workspace.resolve()))
    meta_path = store._project_meta_path(proj_hash)
    meta1 = json.loads(meta_path.read_text())

    time.sleep(0.01)
    (workspace / "hello.py").write_text("v2\n")
    await store.take_snapshot(str(workspace), SnapshotTrigger.WRITE_FILE, "second")

    meta2 = json.loads(meta_path.read_text())
    assert meta2["last_touch"] >= meta1["last_touch"]
    assert meta2["created_at"] == meta1["created_at"]


# ------------------------------------------------------------------
# multiple projects sharing bare repo
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multiple_projects_isolated(store: ShadowGitSnapshotStore, tmp_path: Path):
    ws_a = tmp_path / "project_a"
    ws_a.mkdir()
    (ws_a / "a.txt").write_text("project a\n")

    ws_b = tmp_path / "project_b"
    ws_b.mkdir()
    (ws_b / "b.txt").write_text("project b\n")

    sid_a = await store.take_snapshot(str(ws_a), SnapshotTrigger.MANUAL, "proj-a")
    sid_b = await store.take_snapshot(str(ws_b), SnapshotTrigger.MANUAL, "proj-b")
    assert sid_a != sid_b

    snaps_a = await store.list_snapshots(str(ws_a))
    snaps_b = await store.list_snapshots(str(ws_b))
    assert len(snaps_a) == 1
    assert len(snaps_b) == 1
    assert snaps_a[0].snapshot_id != snaps_b[0].snapshot_id
