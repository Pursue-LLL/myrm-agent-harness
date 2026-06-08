"""Tests for workspace isolation (COW clone + sync back).

Validates:
1. _clone_workspace creates correct directory structure via COW copy
2. _clone_workspace skips heavyweight directories (node_modules, .git, etc.)
3. _clone_workspace rejects oversized workspaces (max_bytes guard)
4. _sync_tree works correctly for syncing back changes
5. isolated_workspace context manager lifecycle
"""

from pathlib import Path

import pytest

from myrm_agent_harness.agent.sub_agents.workspace_isolation import (
    WorkspaceCloneTooLargeError,
    _clone_workspace,
    _sync_tree,
    isolated_workspace,
)


@pytest.fixture
def parent_workspace(tmp_path: Path) -> Path:
    """Create a parent workspace with sample files."""
    ws = tmp_path / "parent_ws"
    ws.mkdir()
    (ws / "file1.txt").write_text("hello")
    (ws / "subdir").mkdir()
    (ws / "subdir" / "file2.py").write_text("print('test')")
    (ws / "subdir" / "nested").mkdir()
    (ws / "subdir" / "nested" / "deep.json").write_text('{"key": "value"}')
    return ws


class TestCloneWorkspace:
    def test_creates_directory_structure(self, parent_workspace: Path, tmp_path: Path):
        dst = tmp_path / "clone"
        dst.mkdir()
        count = _clone_workspace(parent_workspace, dst)

        assert count == 3
        assert (dst / "file1.txt").exists()
        assert (dst / "subdir" / "file2.py").exists()
        assert (dst / "subdir" / "nested" / "deep.json").exists()

    def test_files_are_cloned_not_hardlinked(
        self, parent_workspace: Path, tmp_path: Path
    ):
        dst = tmp_path / "clone"
        dst.mkdir()
        _clone_workspace(parent_workspace, dst)

        src_stat = (parent_workspace / "file1.txt").stat()
        dst_stat = (dst / "file1.txt").stat()
        # They should NOT share the same inode (true isolation)
        assert src_stat.st_ino != dst_stat.st_ino

    def test_content_matches(self, parent_workspace: Path, tmp_path: Path):
        dst = tmp_path / "clone"
        dst.mkdir()
        _clone_workspace(parent_workspace, dst)

        assert (dst / "file1.txt").read_text() == "hello"
        assert (dst / "subdir" / "file2.py").read_text() == "print('test')"
        assert (
            dst / "subdir" / "nested" / "deep.json"
        ).read_text() == '{"key": "value"}'

    def test_empty_directory(self, tmp_path: Path):
        src = tmp_path / "empty_src"
        src.mkdir()
        dst = tmp_path / "empty_dst"
        dst.mkdir()
        count = _clone_workspace(src, dst)
        assert count == 0

    def test_skips_node_modules(self, tmp_path: Path):
        src = tmp_path / "src_ws"
        src.mkdir()
        (src / "index.js").write_text("console.log('hi')")
        nm = src / "node_modules"
        nm.mkdir()
        (nm / "lodash.js").write_text("module.exports = {}")

        dst = tmp_path / "dst_ws"
        dst.mkdir()
        count = _clone_workspace(src, dst)

        assert count == 1
        assert (dst / "index.js").exists()
        assert not (dst / "node_modules").exists()

    def test_skips_git_and_pycache(self, tmp_path: Path):
        src = tmp_path / "src_ws"
        src.mkdir()
        (src / "main.py").write_text("print(1)")
        (src / ".git").mkdir()
        (src / ".git" / "HEAD").write_text("ref: refs/heads/main")
        (src / "__pycache__").mkdir()
        (src / "__pycache__" / "main.cpython-313.pyc").write_bytes(b"\x00")

        dst = tmp_path / "dst_ws"
        dst.mkdir()
        count = _clone_workspace(src, dst)

        assert count == 1
        assert (dst / "main.py").exists()
        assert not (dst / ".git").exists()
        assert not (dst / "__pycache__").exists()

    def test_skips_multiple_heavyweight_dirs(self, tmp_path: Path):
        src = tmp_path / "src_ws"
        src.mkdir()
        (src / "app.ts").write_text("export default {}")
        for dirname in ("dist", "build", ".next", ".venv", "venv", ".tox"):
            d = src / dirname
            d.mkdir()
            (d / "artifact.bin").write_bytes(b"\xff" * 100)

        dst = tmp_path / "dst_ws"
        dst.mkdir()
        count = _clone_workspace(src, dst)

        assert count == 1
        assert (dst / "app.ts").exists()
        for dirname in ("dist", "build", ".next", ".venv", "venv", ".tox"):
            assert not (dst / dirname).exists()

    def test_rejects_oversized_workspace(self, tmp_path: Path):
        src = tmp_path / "big_ws"
        src.mkdir()
        (src / "data.bin").write_bytes(b"\x00" * (2 * 1024 * 1024))

        dst = tmp_path / "dst_ws"
        dst.mkdir()

        with pytest.raises(WorkspaceCloneTooLargeError, match="Cannot create isolated copy"):
            _clone_workspace(src, dst, max_bytes=1024 * 1024)


class TestSyncTree:
    def test_syncs_additions_modifications_deletions(self, tmp_path: Path):
        src = tmp_path / "src"
        src.mkdir()
        dst = tmp_path / "dst"
        dst.mkdir()

        # Initial state in dst
        (dst / "file1.txt").write_text("old")
        (dst / "file2.txt").write_text("delete_me")

        # New state in src
        (src / "file1.txt").write_text("new")  # Modified
        (src / "file3.txt").write_text("added")  # Added
        # file2 is deleted

        _sync_tree(src, dst)

        assert (dst / "file1.txt").read_text() == "new"
        assert not (dst / "file2.txt").exists()
        assert (dst / "file3.txt").read_text() == "added"

    def test_ignores_git_directory(self, tmp_path: Path):
        src = tmp_path / "src"
        src.mkdir()
        dst = tmp_path / "dst"
        dst.mkdir()

        # Setup .git in dst (parent workspace)
        dst_git = dst / ".git"
        dst_git.mkdir()
        (dst_git / "config").write_text("parent_config")

        # Setup .git in src (child workspace)
        src_git = src / ".git"
        src_git.mkdir()
        (src_git / "config").write_text("child_config")
        (src_git / "new_git_file").write_text("should_not_sync")

        _sync_tree(src, dst)

        # Verify .git in dst was NOT overwritten or modified
        assert (dst_git / "config").read_text() == "parent_config"
        assert not (dst_git / "new_git_file").exists()


class TestIsolatedWorkspace:
    @pytest.mark.asyncio
    async def test_creates_and_cleans_up(self, parent_workspace: Path):
        child_path = None
        async with isolated_workspace(parent_workspace) as (child_ws, _sync_back):
            child_path = child_ws
            assert child_ws.exists()
            assert (child_ws / "file1.txt").exists()
            assert (child_ws / "subdir" / "file2.py").exists()

        assert not child_path.exists()

    @pytest.mark.asyncio
    async def test_sync_back_callable(self, parent_workspace: Path):
        async with isolated_workspace(parent_workspace) as (child_ws, sync_back):
            (child_ws / "file1.txt").write_text("changed")
            (child_ws / "new_file.txt").write_text("added")
            (child_ws / "subdir" / "file2.py").unlink()

            await sync_back()

        assert (parent_workspace / "file1.txt").read_text() == "changed"
        assert (parent_workspace / "new_file.txt").read_text() == "added"
        assert not (parent_workspace / "subdir" / "file2.py").exists()

    @pytest.mark.asyncio
    async def test_cleanup_on_exception(self, parent_workspace: Path):
        child_path = None
        with pytest.raises(ValueError):
            async with isolated_workspace(parent_workspace) as (child_ws, _sync_back):
                child_path = child_ws
                raise ValueError("Simulated error")

        assert not child_path.exists()
