"""Tests for ShadowGitSnapshotStore — core shadow git snapshot operations.

Covers: take_snapshot, restore, diff, list_snapshots, delete_snapshot, cleanup,
        no-change skip (diff-index), CAS concurrency safety (update-ref),
        oversized workspace rejection, root/home rejection, env isolation,
        pre-rollback on restore, structured commit messages.
"""

from __future__ import annotations

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
# delete_snapshot (only the newest snapshot is deletable)
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_snapshot_removes_newest(store: ShadowGitSnapshotStore, workspace: Path):
    """Deleting the newest snapshot detaches the project ref to its parent."""
    await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "first")
    (workspace / "hello.py").write_text("v2\n")
    await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "second")
    snaps = await store.list_snapshots(str(workspace))
    newest = snaps[0]

    assert await store.delete_snapshot(newest.snapshot_id) is True

    remaining = await store.list_snapshots(str(workspace))
    assert len(remaining) == 1
    assert remaining[0].snapshot_id != newest.snapshot_id


@pytest.mark.asyncio
async def test_delete_snapshot_intermediate_returns_false(store: ShadowGitSnapshotStore, workspace: Path):
    """Intermediate snapshots in the linear commit chain cannot be deleted."""
    await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "first")
    (workspace / "hello.py").write_text("v2\n")
    await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "second")
    snaps = await store.list_snapshots(str(workspace))
    oldest = snaps[-1]

    assert await store.delete_snapshot(oldest.snapshot_id) is False


@pytest.mark.asyncio
async def test_delete_snapshot_unknown_id_returns_false(store: ShadowGitSnapshotStore):
    """Deleting an unknown snapshot id is a no-op returning False."""
    assert await store.delete_snapshot("deadbeefdeadbeefdeadbeefdeadbeefdeadbeef") is False


@pytest.mark.asyncio
async def test_delete_snapshot_cas_rejects_stale_ref(store: ShadowGitSnapshotStore, workspace: Path):
    """CAS ensures a concurrent take_snapshot (ref moved) cannot be rolled back."""
    await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "first")
    snaps = await store.list_snapshots(str(workspace))
    old_id = snaps[-1].snapshot_id

    (workspace / "hello.py").write_text("v2\n")
    await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "second")

    # Ref head is now the second snapshot; deleting the stale first one must fail.
    assert await store.delete_snapshot(old_id) is False
    remaining = await store.list_snapshots(str(workspace))
    assert len(remaining) == 2


# ------------------------------------------------------------------
# cleanup
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cleanup_keeps_most_recent(store: ShadowGitSnapshotStore, workspace: Path):
    """Cleanup keeps the newest snapshots and severs older ones from the chain."""
    for i in range(6):
        (workspace / "hello.py").write_text(f"v{i}\n")
        await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, f"iter-{i}")

    before = await store.list_snapshots(str(workspace), limit=100)
    assert len(before) == 6

    deleted = await store.cleanup(str(workspace), max_snapshots=3)
    assert deleted == 3

    after = await store.list_snapshots(str(workspace), limit=100)
    assert len(after) == 3
    assert [s.snapshot_id for s in after] == [s.snapshot_id for s in before[:3]]
    # Removed snapshots are no longer resolvable.
    for removed in before[3:]:
        assert await store.find_project_for_commit(removed.snapshot_id) == (None, None)


@pytest.mark.asyncio
async def test_cleanup_under_limit_noop(store: ShadowGitSnapshotStore, workspace: Path):
    """Cleanup is a no-op when snapshot count is within the limit."""
    for i in range(3):
        (workspace / "hello.py").write_text(f"v{i}\n")
        await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, f"iter-{i}")

    deleted = await store.cleanup(str(workspace), max_snapshots=5)
    assert deleted == 0
    assert len(await store.list_snapshots(str(workspace), limit=100)) == 3


@pytest.mark.asyncio
async def test_cleanup_graft_failure_returns_zero(store: ShadowGitSnapshotStore, workspace: Path, monkeypatch):
    """A failed git replace during cleanup reports 0 deletions instead of raising."""
    for i in range(6):
        (workspace / "hello.py").write_text(f"v{i}\n")
        await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, f"iter-{i}")

    real_run = store._run_cmd

    async def selective_fail(*args, **kwargs):
        if args[:2] == ("git", "replace"):
            raise RuntimeError("replace failed")
        return await real_run(*args, **kwargs)

    monkeypatch.setattr(store, "_run_cmd", selective_fail)
    deleted = await store.cleanup(str(workspace), max_snapshots=3)
    assert deleted == 0


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

    await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "with large")

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

    await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "with node_modules")
    snaps = await store.list_snapshots(str(workspace))
    assert snaps[0].file_count == 2  # hello.py + sub/data.txt


@pytest.mark.asyncio
async def test_default_excludes_pycache(store: ShadowGitSnapshotStore, workspace: Path):
    """__pycache__/ should be excluded."""
    cache = workspace / "__pycache__"
    cache.mkdir()
    (cache / "module.pyc").write_bytes(b"\x00" * 100)

    await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "with pycache")
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
    """Description should surface the business text without the internal format prefix."""
    await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "my custom desc")
    snaps = await store.list_snapshots(str(workspace))
    assert snaps[0].description == "my custom desc"


@pytest.mark.asyncio
async def test_list_snapshots_empty_description_has_no_prefix(store: ShadowGitSnapshotStore, workspace: Path):
    """A snapshot with an empty description must not leak the stored line prefix."""
    await store.take_snapshot(str(workspace), SnapshotTrigger.EXECUTE_TERMINAL, "")
    snaps = await store.list_snapshots(str(workspace))
    assert snaps[0].description == ""
    assert "snapshot" not in snaps[0].description


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


# ------------------------------------------------------------------
# get_snapshot_info: metadata / description parsing and error paths
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_snapshot_info_parses_metadata_and_description(store: ShadowGitSnapshotStore, workspace: Path):
    """get_snapshot_info returns full metadata with stripped description prefix."""
    await store.take_snapshot(
        str(workspace),
        SnapshotTrigger.MANUAL,
        "my info desc",
        metadata={"external_effects": ("database",), "agent_id": "agent-x"},
    )
    sid = (await store.list_snapshots(str(workspace)))[0].snapshot_id

    info = await store.get_snapshot_info(sid)
    assert info is not None
    assert info.snapshot_id == sid
    assert info.description == "my info desc"
    assert info.trigger == SnapshotTrigger.MANUAL
    assert info.metadata.get("external_effects") == ["database"]
    assert info.metadata.get("agent_id") == "agent-x"


@pytest.mark.asyncio
async def test_get_snapshot_info_invalid_hash_returns_none(store: ShadowGitSnapshotStore, workspace: Path):
    """Invalid commit hashes are rejected without raising."""
    await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "x")
    assert await store.get_snapshot_info("not-a-commit") is None


@pytest.mark.asyncio
async def test_get_snapshot_info_unknown_commit_returns_none(store: ShadowGitSnapshotStore, workspace: Path):
    """Unknown but well-formed commit hashes return None."""
    await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "x")
    bogus = "f" * 40
    assert await store.get_snapshot_info(bogus) is None


@pytest.mark.asyncio
async def test_get_snapshot_info_empty_description_no_prefix(store: ShadowGitSnapshotStore, workspace: Path):
    """Empty description must not leak the internal snapshot prefix."""
    await store.take_snapshot(str(workspace), SnapshotTrigger.EXECUTE_TERMINAL, "")
    sid = (await store.list_snapshots(str(workspace)))[0].snapshot_id
    info = await store.get_snapshot_info(sid)
    assert info is not None
    assert info.description == ""


# ------------------------------------------------------------------
# diff: numstat binary handling and failure branch
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_diff_with_binary_file_reports_null_stats(store: ShadowGitSnapshotStore, workspace: Path):
    """Binary files in diff numstat use '-' and must not crash parsing."""
    sid = await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "baseline")
    (workspace / "bin.dat").write_bytes(b"\x00\x01\x02")
    diff = await store.diff(sid)
    assert diff.total_changes >= 1
    assert all(c.path for c in diff.changes)


@pytest.mark.asyncio
async def test_diff_unknown_snapshot_returns_empty(store: ShadowGitSnapshotStore, workspace: Path):
    """Diff against an unknown snapshot returns an empty diff instead of raising."""
    await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "x")
    diff = await store.diff("b" * 40)
    assert diff.total_changes == 0


# ------------------------------------------------------------------
# restore: unknown commit / missing workspace
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_restore_unknown_commit_fails(store: ShadowGitSnapshotStore, workspace: Path):
    """Restoring an unknown snapshot returns a failure result."""
    await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "x")
    result = await store.restore("a" * 40)
    assert result.success is False
    assert result.files_restored == 0


@pytest.mark.asyncio
async def test_restore_missing_workspace_fails(store: ShadowGitSnapshotStore, workspace: Path):
    """Restore reports failure when the workspace no longer exists."""
    sid = await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "x")
    (workspace / "hello.py").write_text("v2\n")
    import shutil

    shutil.rmtree(workspace)
    result = await store.restore(sid)
    assert result.success is False
    assert result.error is not None


# ------------------------------------------------------------------
# edge coverage: default path / corrupt metadata / oversized rejection
# ------------------------------------------------------------------


def test_default_store_path_uses_myrm_data_dir(monkeypatch):
    import myrm_agent_harness.agent.file_snapshot.shadow_git_store as sgs

    monkeypatch.setenv("MYRM_DATA_DIR", "/data/myrm")
    assert sgs._default_store_path() == Path("/data/myrm/file_snapshots")


def test_default_store_path_fallback(monkeypatch):
    import myrm_agent_harness.agent.file_snapshot.shadow_git_store as sgs

    monkeypatch.delenv("MYRM_DATA_DIR", raising=False)
    assert sgs._default_store_path() == Path.home() / ".myrm" / "file_snapshots"


@pytest.mark.asyncio
async def test_touch_project_recovers_corrupt_meta(store: ShadowGitSnapshotStore, workspace: Path):
    """Corrupt project metadata is rebuilt on the next snapshot."""
    import json

    await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "first")
    meta_path = store._project_meta_path(_project_hash(str(workspace.resolve())))
    meta_path.write_text("{corrupt")

    (workspace / "hello.py").write_text("v2\n")
    await store.take_snapshot(str(workspace), SnapshotTrigger.WRITE_FILE, "second")
    meta = json.loads(meta_path.read_text())
    assert meta["workdir"] == str(workspace.resolve())


@pytest.mark.asyncio
async def test_take_snapshot_rejects_oversized_workspace(store: ShadowGitSnapshotStore, workspace: Path, monkeypatch):
    """A workspace exceeding the file-count limit is rejected."""
    import myrm_agent_harness.agent.file_snapshot.shadow_git_maintenance as maint

    monkeypatch.setattr(maint, "_MAX_FILE_COUNT", 1)
    with pytest.raises(ValueError, match="exceeds file count"):
        await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL)


# ------------------------------------------------------------------
# edge coverage: restore pre-rollback failure / diff git failure
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_restore_pre_rollback_failure_continues(store: ShadowGitSnapshotStore, workspace: Path, monkeypatch):
    """A failed pre-rollback snapshot must not abort the restore itself."""
    sid = await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "baseline")
    (workspace / "hello.py").write_text("changed\n")

    async def fail_take(*args, **kwargs):
        raise RuntimeError("pre-rollback failed")

    monkeypatch.setattr(store, "take_snapshot", fail_take)
    result = await store.restore(sid)
    assert result.success is True
    assert result.pre_rollback_snapshot_id is None


@pytest.mark.asyncio
async def test_diff_handles_git_failure(store: ShadowGitSnapshotStore, workspace: Path, monkeypatch):
    """A git failure during diff returns an empty diff instead of raising."""
    sid = await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "baseline")
    (workspace / "hello.py").write_text("changed\n")

    real_run = store._run_cmd

    async def selective_fail(*args, **kwargs):
        if args[:2] == ("git", "add"):
            raise RuntimeError("git add failed")
        return await real_run(*args, **kwargs)

    monkeypatch.setattr(store, "_run_cmd", selective_fail)
    diff = await store.diff(sid)
    assert diff.total_changes == 0


@pytest.mark.asyncio
async def test_diff_ignores_malformed_lines(store: ShadowGitSnapshotStore, workspace: Path, monkeypatch):
    """Blank and malformed numstat/name-status lines are skipped."""
    sid = await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "baseline")
    (workspace / "hello.py").write_text("changed\n")

    real_run = store._run_cmd

    async def fake_run_cmd(*args, **kwargs):
        if args[0] == "git" and args[1] == "diff-tree":
            if "--numstat" in args:
                return "\nbad-line\twithout-tabs\n"
            return "\nmalformed-line\n"
        return await real_run(*args, **kwargs)

    monkeypatch.setattr(store, "_run_cmd", fake_run_cmd)
    diff = await store.diff(sid)
    assert diff.total_changes == 0


# ------------------------------------------------------------------
# edge coverage: list_snapshots / get_snapshot_info parsing failures
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_snapshots_bad_created_at(store: ShadowGitSnapshotStore, workspace: Path, monkeypatch):
    """A non-numeric created_at falls back to 0.0 instead of raising."""
    await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "x")

    async def fake_run_cmd(*args, **kwargs):
        if args[0] == "git" and args[1] == "log":
            return f"{'a' * 40}\nnot-a-number\nsnapshot manual: test\n\n---END---"
        return ""

    monkeypatch.setattr(store, "_run_cmd", fake_run_cmd)
    snaps = await store.list_snapshots(str(workspace))
    assert len(snaps) == 1
    assert snaps[0].created_at == 0.0


@pytest.mark.asyncio
async def test_get_snapshot_info_git_failure(store: ShadowGitSnapshotStore, workspace: Path, monkeypatch):
    await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "x")
    sid = (await store.list_snapshots(str(workspace)))[0].snapshot_id

    real_run = store._run_cmd

    async def selective_fail(*args, **kwargs):
        if args[0] == "git" and args[1] == "log":
            raise RuntimeError("git log failed")
        return await real_run(*args, **kwargs)

    monkeypatch.setattr(store, "_run_cmd", selective_fail)
    assert await store.get_snapshot_info(sid) is None


@pytest.mark.asyncio
async def test_get_snapshot_info_short_log(store: ShadowGitSnapshotStore, workspace: Path, monkeypatch):
    await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "x")
    sid = (await store.list_snapshots(str(workspace)))[0].snapshot_id

    async def fake_run_cmd(*args, **kwargs):
        if args[0] == "git" and args[1] == "log":
            return "only-one-line"
        return ""

    monkeypatch.setattr(store, "_run_cmd", fake_run_cmd)
    assert await store.get_snapshot_info(sid) is None


@pytest.mark.asyncio
async def test_get_snapshot_info_bad_created_at(store: ShadowGitSnapshotStore, workspace: Path, monkeypatch):
    await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "x")
    sid = (await store.list_snapshots(str(workspace)))[0].snapshot_id

    async def fake_run_cmd(*args, **kwargs):
        if args[0] == "git" and args[1] == "log":
            return f"{sid}\nnot-a-number\nsnapshot manual: x\n\n"
        return ""

    monkeypatch.setattr(store, "_run_cmd", fake_run_cmd)
    info = await store.get_snapshot_info(sid)
    assert info is not None
    assert info.created_at == 0.0


# ------------------------------------------------------------------
# edge coverage: delete_snapshot failure branches
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_snapshot_invalid_format_returns_false(store: ShadowGitSnapshotStore, workspace: Path):
    """A malformed snapshot id is rejected before any git lookup."""
    await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "x")
    assert await store.delete_snapshot("not-a-hash") is False


@pytest.mark.asyncio
async def test_delete_snapshot_rev_parse_failure(store: ShadowGitSnapshotStore, workspace: Path, monkeypatch):
    sid = await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "x")

    real_run = store._run_cmd

    async def selective_fail(*args, **kwargs):
        if args[0] == "git" and args[1] == "rev-parse" and "--verify" in args:
            raise RuntimeError("rev-parse failed")
        return await real_run(*args, **kwargs)

    monkeypatch.setattr(store, "_run_cmd", selective_fail)
    assert await store.delete_snapshot(sid) is False


@pytest.mark.asyncio
async def test_delete_snapshot_only_commit_detaches_ref(store: ShadowGitSnapshotStore, workspace: Path):
    """Deleting the only snapshot detaches the project ref entirely."""
    sid = await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "only")
    assert await store.delete_snapshot(sid) is True
    assert await store.list_snapshots(str(workspace)) == []


@pytest.mark.asyncio
async def test_delete_snapshot_update_ref_failure(store: ShadowGitSnapshotStore, workspace: Path, monkeypatch):
    await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "first")
    (workspace / "hello.py").write_text("v2\n")
    sid = await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "second")

    real_run = store._run_cmd

    async def fail_update_ref(*args, **kwargs):
        if "update-ref" in args:
            raise RuntimeError("update-ref failed")
        return await real_run(*args, **kwargs)

    monkeypatch.setattr(store, "_run_cmd", fail_update_ref)
    assert await store.delete_snapshot(sid) is False
