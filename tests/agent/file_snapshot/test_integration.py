"""Integration test: factory -> ShadowGitSnapshotStore full lifecycle.

Non-mocked end-to-end test covering the complete snapshot lifecycle
through the factory, verifying real git operations work correctly.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from myrm_agent_harness.agent.file_snapshot.factory import create_file_snapshot_store
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


@pytest.fixture(autouse=True)
def _reset_factory_cache():
    import myrm_agent_harness.agent.file_snapshot.factory as factory_mod

    factory_mod._cached_store = None
    yield
    factory_mod._cached_store = None


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "integration_workspace"
    ws.mkdir()
    (ws / "app.py").write_text("def main(): pass\n")
    (ws / "config.yaml").write_text("key: value\n")
    (ws / "src").mkdir()
    (ws / "src" / "utils.py").write_text("def helper(): return True\n")
    return ws


@pytest.mark.asyncio
async def test_factory_to_snapshot_full_lifecycle(workspace: Path):
    """Factory -> take -> modify -> take -> diff -> restore -> verify."""
    store = await create_file_snapshot_store()
    assert isinstance(store, ShadowGitSnapshotStore)

    sid1 = await store.take_snapshot(str(workspace), SnapshotTrigger.WRITE_FILE, "initial")
    assert len(sid1) == 40

    (workspace / "app.py").write_text("def main(): print('v2')\n")
    (workspace / "new_module.py").write_text("class Foo: pass\n")

    sid2 = await store.take_snapshot(str(workspace), SnapshotTrigger.WRITE_FILE, "after changes")
    assert sid1 != sid2

    diff = await store.diff(sid1)
    assert diff.total_changes > 0
    changed_paths = {c.path for c in diff.changes}
    assert "app.py" in changed_paths
    assert "new_module.py" in changed_paths

    result = await store.restore(sid1)
    assert result.success is True
    assert result.pre_rollback_snapshot_id is not None
    assert (workspace / "app.py").read_text() == "def main(): pass\n"

    snaps = await store.list_snapshots(str(workspace))
    assert len(snaps) >= 2  # initial + after changes (pre-rollback may skip via diff-index)


@pytest.mark.asyncio
async def test_factory_caching_across_snapshots(workspace: Path):
    """Factory should return the same cached store instance."""
    store1 = await create_file_snapshot_store()
    store2 = await create_file_snapshot_store()
    assert store1 is store2

    await store1.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "from store1")
    snaps = await store2.list_snapshots(str(workspace))
    assert len(snaps) == 1


@pytest.mark.asyncio
async def test_no_change_skip_through_factory(workspace: Path):
    """No-change skip should work through factory-created store."""
    store = await create_file_snapshot_store()
    sid1 = await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "first")
    sid2 = await store.take_snapshot(str(workspace), SnapshotTrigger.MANUAL, "second")
    assert sid1 == sid2  # no-change skip
