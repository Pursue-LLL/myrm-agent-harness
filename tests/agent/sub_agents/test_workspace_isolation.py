"""Tests for workspace isolation (hardlink tree + sync back).

Validates:
1. _hardlink_tree creates correct directory structure with hardlinks
2. _sync_tree works correctly for syncing back changes
3. isolated_workspace context manager lifecycle
"""

from pathlib import Path

import pytest

from myrm_agent_harness.agent.sub_agents.workspace_isolation import (
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
