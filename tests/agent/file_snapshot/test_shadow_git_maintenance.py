"""Tests for ShadowGitMaintenance mixin — pruning, repair, workspace validation.

Covers: is_oversized_workspace, drop_oversized_from_index, find_project_for_commit,
        maybe_prune, orphan detection, global size cap, repair_if_corrupted.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import pytest

from myrm_agent_harness.agent.file_snapshot.shadow_git_store import ShadowGitSnapshotStore
from myrm_agent_harness.agent.file_snapshot.types import SnapshotTrigger


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
    (ws / "file.txt").write_text("content\n")
    return ws


# ------------------------------------------------------------------
# is_oversized_workspace
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_normal_workspace_not_oversized(store: ShadowGitSnapshotStore, workspace: Path):
    assert await store.is_oversized_workspace(str(workspace)) is False


@pytest.mark.asyncio
async def test_nonexistent_workspace_not_oversized(store: ShadowGitSnapshotStore, tmp_path: Path):
    """Nonexistent dir yields zero files from os.walk, not oversized."""
    assert await store.is_oversized_workspace(str(tmp_path / "gone")) is False


# ------------------------------------------------------------------
# find_project_for_commit
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_find_project_for_commit_found(store: ShadowGitSnapshotStore, workspace: Path):
    sid = await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "test")
    proj_hash, workdir = await store.find_project_for_commit(sid)
    assert proj_hash is not None
    assert workdir == str(workspace.resolve())


@pytest.mark.asyncio
async def test_find_project_for_commit_not_found(store: ShadowGitSnapshotStore, workspace: Path):
    await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "test")
    proj_hash, workdir = await store.find_project_for_commit("a" * 40)
    assert proj_hash is None
    assert workdir is None


# ------------------------------------------------------------------
# maybe_prune — idempotent, interval-gated
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_maybe_prune_creates_marker(store: ShadowGitSnapshotStore, workspace: Path):
    await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "test")
    marker = store._store_path / ".last_prune"
    assert marker.exists()


@pytest.mark.asyncio
async def test_maybe_prune_skips_within_interval(store: ShadowGitSnapshotStore, workspace: Path):
    await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "test")
    marker = store._store_path / ".last_prune"
    mtime_before = marker.stat().st_mtime

    await store.maybe_prune()
    mtime_after = marker.stat().st_mtime
    assert mtime_after == mtime_before


# ------------------------------------------------------------------
# orphan project detection
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prune_orphan_removes_deleted_workspace(store: ShadowGitSnapshotStore, tmp_path: Path):
    ws = tmp_path / "ephemeral"
    ws.mkdir()
    (ws / "f.txt").write_text("data\n")
    await store.take_snapshot(str(ws), SnapshotTrigger.MANUAL, "ephemeral")

    projects_dir = store._git_dir / "projects"
    assert any(projects_dir.iterdir())

    import shutil
    shutil.rmtree(ws)

    await store._prune_orphan_projects()

    remaining = [f for f in projects_dir.iterdir() if f.suffix == ".json"]
    assert len(remaining) == 0


# ------------------------------------------------------------------
# repair_if_corrupted
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repair_detects_missing_head(store: ShadowGitSnapshotStore, workspace: Path):
    await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "test")
    (store._git_dir / "HEAD").unlink()

    repaired = await store.repair_if_corrupted()
    assert repaired is True


@pytest.mark.asyncio
async def test_repair_detects_empty_head(store: ShadowGitSnapshotStore, workspace: Path):
    await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "test")
    (store._git_dir / "HEAD").write_text("")

    repaired = await store.repair_if_corrupted()
    assert repaired is True


@pytest.mark.asyncio
async def test_repair_noop_when_healthy(store: ShadowGitSnapshotStore, workspace: Path):
    await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "test")
    repaired = await store.repair_if_corrupted()
    assert repaired is False


# ------------------------------------------------------------------
# project metadata
# ------------------------------------------------------------------


# ------------------------------------------------------------------
# drop_oversized_from_index
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_drop_oversized_from_index(store: ShadowGitSnapshotStore, workspace: Path):
    """Files > 10MB should be dropped from the git index."""
    large = workspace / "oversized.bin"
    large.write_bytes(b"\x00" * (11 * 1024 * 1024))

    sid = await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "with oversized")
    snaps = await store.list_snapshots(str(workspace))
    assert snaps[0].file_count == 1  # only file.txt, not oversized.bin


# ------------------------------------------------------------------
# _bare_env isolation
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bare_env_strips_work_tree(store: ShadowGitSnapshotStore, workspace: Path):
    """_bare_env() should not contain GIT_WORK_TREE or GIT_INDEX_FILE."""
    await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "test")
    env = store._bare_env()
    assert "GIT_WORK_TREE" not in env
    assert "GIT_INDEX_FILE" not in env
    assert env["GIT_DIR"] == str(store._git_dir)


# ------------------------------------------------------------------
# project metadata
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_project_metadata_created(store: ShadowGitSnapshotStore, workspace: Path):
    await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "test")
    projects_dir = store._git_dir / "projects"
    meta_files = list(projects_dir.glob("*.json"))
    assert len(meta_files) == 1
    meta = json.loads(meta_files[0].read_text())
    assert "workdir" in meta
    assert "created_at" in meta
    assert "last_touch" in meta
