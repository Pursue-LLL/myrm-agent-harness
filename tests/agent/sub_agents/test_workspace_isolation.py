"""Tests for workspace isolation (COW clone + sync back).

Validates:
1. _clone_workspace creates correct directory structure via COW copy
2. _clone_workspace skips heavyweight directories (node_modules, .git, etc.)
3. _clone_workspace rejects oversized workspaces (max_bytes guard)
4. _sync_tree works correctly for syncing back changes
5. _merge_tree_additive merges without deleting dst-only files
6. _estimate_clone_size respects ignore patterns and handles edge cases
7. isolated_workspace context manager lifecycle
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from myrm_agent_harness.agent.sub_agents.workspace_isolation import (
    WorkspaceCloneTooLargeError,
    _CLONE_IGNORE_DIRS,
    _clone_workspace,
    _estimate_clone_size,
    _merge_tree_additive,
    _sync_tree,
    _sync_workspace_back,
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


    def test_preserves_clone_ignored_dirs_in_dst(self, tmp_path: Path):
        """Regression: _sync_tree must not delete directories that were
        excluded during clone (e.g. node_modules, .venv)."""
        src = tmp_path / "child"
        src.mkdir()
        dst = tmp_path / "parent"
        dst.mkdir()

        (dst / "app.ts").write_text("old")
        (dst / "node_modules").mkdir()
        (dst / "node_modules" / "lodash.js").write_text("module.exports={}")
        (dst / ".venv").mkdir()
        (dst / ".venv" / "pyvenv.cfg").write_text("home=/usr/bin")
        (dst / "__pycache__").mkdir()
        (dst / "__pycache__" / "app.cpython-313.pyc").write_bytes(b"\x00")

        (src / "app.ts").write_text("new")

        _sync_tree(src, dst)

        assert (dst / "app.ts").read_text() == "new"
        assert (dst / "node_modules" / "lodash.js").exists()
        assert (dst / ".venv" / "pyvenv.cfg").exists()
        assert (dst / "__pycache__" / "app.cpython-313.pyc").exists()


class TestEstimateCloneSize:
    def test_excludes_ignored_dirs(self, tmp_path: Path):
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "main.py").write_text("x" * 100)
        nm = ws / "node_modules"
        nm.mkdir()
        (nm / "big.js").write_bytes(b"\x00" * 5000)

        size = _estimate_clone_size(ws, _CLONE_IGNORE_DIRS)
        assert size == 100

    def test_empty_dir_returns_zero(self, tmp_path: Path):
        ws = tmp_path / "empty"
        ws.mkdir()
        assert _estimate_clone_size(ws, _CLONE_IGNORE_DIRS) == 0

    def test_handles_unreadable_file(self, tmp_path: Path):
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "ok.txt").write_text("data")

        with patch("os.path.getsize", side_effect=OSError("perm denied")):
            size = _estimate_clone_size(ws, _CLONE_IGNORE_DIRS)
        assert size == 0

    def test_nested_ignored_dirs(self, tmp_path: Path):
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "src").mkdir()
        (ws / "src" / "app.py").write_text("x" * 50)
        deep_nm = ws / "src" / "node_modules"
        deep_nm.mkdir()
        (deep_nm / "pkg.js").write_bytes(b"\x00" * 3000)

        size = _estimate_clone_size(ws, _CLONE_IGNORE_DIRS)
        assert size == 50


class TestMergeTreeAdditive:
    def test_adds_new_files_to_dst(self, tmp_path: Path):
        src = tmp_path / "src"
        src.mkdir()
        dst = tmp_path / "dst"
        dst.mkdir()

        (src / "new.txt").write_text("added")
        (dst / "existing.txt").write_text("keep")

        _merge_tree_additive(src, dst)

        assert (dst / "new.txt").read_text() == "added"
        assert (dst / "existing.txt").read_text() == "keep"

    def test_overwrites_modified_files(self, tmp_path: Path):
        src = tmp_path / "src"
        src.mkdir()
        dst = tmp_path / "dst"
        dst.mkdir()

        (dst / "file.txt").write_text("old")
        (src / "file.txt").write_text("new")

        _merge_tree_additive(src, dst)

        assert (dst / "file.txt").read_text() == "new"

    def test_does_not_delete_dst_only_files(self, tmp_path: Path):
        src = tmp_path / "src"
        src.mkdir()
        dst = tmp_path / "dst"
        dst.mkdir()

        (dst / "only_in_dst.txt").write_text("keep me")
        (src / "from_src.txt").write_text("new")

        _merge_tree_additive(src, dst)

        assert (dst / "only_in_dst.txt").read_text() == "keep me"
        assert (dst / "from_src.txt").read_text() == "new"

    def test_skips_ignored_dirs(self, tmp_path: Path):
        src = tmp_path / "src"
        src.mkdir()
        dst = tmp_path / "dst"
        dst.mkdir()

        nm = src / "node_modules"
        nm.mkdir()
        (nm / "pkg.js").write_text("should not merge")
        (src / "app.ts").write_text("code")

        _merge_tree_additive(src, dst)

        assert (dst / "app.ts").read_text() == "code"
        assert not (dst / "node_modules").exists()

    def test_creates_nested_dirs(self, tmp_path: Path):
        src = tmp_path / "src"
        src.mkdir()
        dst = tmp_path / "dst"
        dst.mkdir()

        (src / "a" / "b").mkdir(parents=True)
        (src / "a" / "b" / "deep.txt").write_text("deep")

        _merge_tree_additive(src, dst)

        assert (dst / "a" / "b" / "deep.txt").read_text() == "deep"

    def test_skips_identical_files(self, tmp_path: Path):
        src = tmp_path / "src"
        src.mkdir()
        dst = tmp_path / "dst"
        dst.mkdir()

        (src / "same.txt").write_text("content")
        (dst / "same.txt").write_text("content")

        old_mtime = (dst / "same.txt").stat().st_mtime_ns
        _merge_tree_additive(src, dst)
        new_mtime = (dst / "same.txt").stat().st_mtime_ns

        assert (dst / "same.txt").read_text() == "content"
        assert old_mtime == new_mtime


class TestSyncTreeAdvanced:
    def test_deletes_nested_dirs_not_in_src(self, tmp_path: Path):
        src = tmp_path / "src"
        src.mkdir()
        dst = tmp_path / "dst"
        dst.mkdir()

        (dst / "stale_dir" / "sub").mkdir(parents=True)
        (dst / "stale_dir" / "sub" / "old.txt").write_text("old")
        (src / "new.txt").write_text("new")

        _sync_tree(src, dst)

        assert not (dst / "stale_dir").exists()
        assert (dst / "new.txt").read_text() == "new"

    def test_creates_new_nested_dirs_from_src(self, tmp_path: Path):
        src = tmp_path / "src"
        src.mkdir()
        dst = tmp_path / "dst"
        dst.mkdir()

        (src / "a" / "b" / "c").mkdir(parents=True)
        (src / "a" / "b" / "c" / "new.txt").write_text("deep")

        _sync_tree(src, dst)

        assert (dst / "a" / "b" / "c" / "new.txt").read_text() == "deep"

    def test_preserves_all_clone_ignored_dirs(self, tmp_path: Path):
        """Verify every entry in _CLONE_IGNORE_DIRS is preserved in dst."""
        src = tmp_path / "child"
        src.mkdir()
        dst = tmp_path / "parent"
        dst.mkdir()

        (src / "code.py").write_text("new")
        (dst / "code.py").write_text("old")

        for dirname in _CLONE_IGNORE_DIRS:
            d = dst / dirname
            d.mkdir()
            (d / "marker.txt").write_text(f"preserve_{dirname}")

        _sync_tree(src, dst)

        assert (dst / "code.py").read_text() == "new"
        for dirname in _CLONE_IGNORE_DIRS:
            assert (dst / dirname / "marker.txt").exists(), (
                f"{dirname} was incorrectly deleted during sync"
            )

    def test_empty_src_clears_dst_files(self, tmp_path: Path):
        src = tmp_path / "src"
        src.mkdir()
        dst = tmp_path / "dst"
        dst.mkdir()

        (dst / "old.txt").write_text("should be deleted")
        (dst / "subdir").mkdir()
        (dst / "subdir" / "old2.txt").write_text("also deleted")

        _sync_tree(src, dst)

        assert not (dst / "old.txt").exists()
        assert not (dst / "subdir").exists()


class TestCloneWorkspaceBoundary:
    def test_exact_max_bytes_passes(self, tmp_path: Path):
        """max_bytes boundary: estimated == max_bytes should pass (only > fails)."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "data.bin").write_bytes(b"\x00" * 1024)

        dst = tmp_path / "dst"
        dst.mkdir()
        count = _clone_workspace(src, dst, max_bytes=1024)
        assert count == 1

    def test_max_bytes_zero_rejects_nonempty(self, tmp_path: Path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "tiny.txt").write_text("x")

        dst = tmp_path / "dst"
        dst.mkdir()
        with pytest.raises(WorkspaceCloneTooLargeError):
            _clone_workspace(src, dst, max_bytes=0)

    def test_binary_files_cloned_correctly(self, tmp_path: Path):
        src = tmp_path / "src"
        src.mkdir()
        binary_data = bytes(range(256)) * 4
        (src / "image.bin").write_bytes(binary_data)

        dst = tmp_path / "dst"
        dst.mkdir()
        _clone_workspace(src, dst)

        assert (dst / "image.bin").read_bytes() == binary_data

    def test_symlinks_are_handled(self, tmp_path: Path):
        """Symlinks should be copied as-is by shutil.copytree."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "real.txt").write_text("target")
        (src / "link.txt").symlink_to(src / "real.txt")

        dst = tmp_path / "dst"
        dst.mkdir()
        count = _clone_workspace(src, dst)

        assert count == 2
        assert (dst / "link.txt").read_text() == "target"


class TestSyncTreeBoundary:
    def test_syncs_binary_files(self, tmp_path: Path):
        src = tmp_path / "src"
        src.mkdir()
        dst = tmp_path / "dst"
        dst.mkdir()

        binary_data = bytes(range(256))
        (src / "bin.dat").write_bytes(binary_data)
        (dst / "bin.dat").write_bytes(b"\x00" * 256)

        _sync_tree(src, dst)

        assert (dst / "bin.dat").read_bytes() == binary_data

    def test_identical_files_not_rewritten(self, tmp_path: Path):
        src = tmp_path / "src"
        src.mkdir()
        dst = tmp_path / "dst"
        dst.mkdir()

        (src / "same.txt").write_text("identical")
        (dst / "same.txt").write_text("identical")

        old_mtime = (dst / "same.txt").stat().st_mtime_ns
        _sync_tree(src, dst)
        new_mtime = (dst / "same.txt").stat().st_mtime_ns

        assert old_mtime == new_mtime

    def test_nested_ignored_dir_in_subdirectory(self, tmp_path: Path):
        """node_modules nested inside a subdirectory should also be preserved."""
        src = tmp_path / "child"
        src.mkdir()
        dst = tmp_path / "parent"
        dst.mkdir()

        (dst / "pkg").mkdir()
        (dst / "pkg" / "node_modules").mkdir()
        (dst / "pkg" / "node_modules" / "dep.js").write_text("dep")
        (dst / "pkg" / "src").mkdir()
        (dst / "pkg" / "src" / "app.js").write_text("old")

        (src / "pkg").mkdir()
        (src / "pkg" / "src").mkdir()
        (src / "pkg" / "src" / "app.js").write_text("new")

        _sync_tree(src, dst)

        assert (dst / "pkg" / "src" / "app.js").read_text() == "new"
        assert (dst / "pkg" / "node_modules" / "dep.js").exists()


class TestMergeTreeAdditiveAdvanced:
    def test_empty_src_leaves_dst_intact(self, tmp_path: Path):
        src = tmp_path / "src"
        src.mkdir()
        dst = tmp_path / "dst"
        dst.mkdir()

        (dst / "keep.txt").write_text("preserved")

        _merge_tree_additive(src, dst)

        assert (dst / "keep.txt").read_text() == "preserved"

    def test_preserves_dst_ignored_dirs(self, tmp_path: Path):
        """Even though merge is additive, ignored dirs in src should not be merged."""
        src = tmp_path / "src"
        src.mkdir()
        dst = tmp_path / "dst"
        dst.mkdir()

        (src / "__pycache__").mkdir()
        (src / "__pycache__" / "mod.pyc").write_bytes(b"\x00")
        (src / ".venv").mkdir()
        (src / ".venv" / "pyvenv.cfg").write_text("home=/usr")
        (src / "app.py").write_text("code")

        (dst / "existing.txt").write_text("keep")

        _merge_tree_additive(src, dst)

        assert (dst / "app.py").read_text() == "code"
        assert (dst / "existing.txt").read_text() == "keep"
        assert not (dst / "__pycache__").exists()
        assert not (dst / ".venv").exists()


class TestEndToEndWorkflow:
    @pytest.mark.asyncio
    async def test_full_lifecycle_with_ignored_dirs(self, tmp_path: Path):
        """E2E: parent has ignored dirs → clone skips them → child modifies →
        sync_back → parent ignored dirs still intact + changes applied."""
        parent = tmp_path / "parent"
        parent.mkdir()
        (parent / "src").mkdir()
        (parent / "src" / "main.py").write_text("original")
        (parent / "node_modules").mkdir()
        (parent / "node_modules" / "lodash.js").write_text("module.exports={}")
        (parent / ".venv").mkdir()
        (parent / ".venv" / "pyvenv.cfg").write_text("home=/usr")
        (parent / "README.md").write_text("old readme")

        async with isolated_workspace(parent) as (child_ws, sync_back):
            assert not (child_ws / "node_modules").exists()
            assert not (child_ws / ".venv").exists()
            assert (child_ws / "src" / "main.py").exists()

            (child_ws / "src" / "main.py").write_text("modified")
            (child_ws / "src" / "new_module.py").write_text("new code")
            (child_ws / "README.md").unlink()

            await sync_back()

        assert (parent / "src" / "main.py").read_text() == "modified"
        assert (parent / "src" / "new_module.py").read_text() == "new code"
        assert not (parent / "README.md").exists()
        assert (parent / "node_modules" / "lodash.js").read_text() == "module.exports={}"
        assert (parent / ".venv" / "pyvenv.cfg").read_text() == "home=/usr"

    @pytest.mark.asyncio
    async def test_no_sync_back_preserves_parent(self, tmp_path: Path):
        """If sync_back is never called, parent should remain unchanged."""
        parent = tmp_path / "parent"
        parent.mkdir()
        (parent / "file.txt").write_text("original")

        async with isolated_workspace(parent) as (child_ws, _sync_back):
            (child_ws / "file.txt").write_text("modified in child")
            (child_ws / "new.txt").write_text("should not appear")

        assert (parent / "file.txt").read_text() == "original"
        assert not (parent / "new.txt").exists()

    @pytest.mark.asyncio
    async def test_temp_dir_naming(self, tmp_path: Path):
        parent = tmp_path / "my_project"
        parent.mkdir()
        (parent / "f.txt").write_text("x")

        async with isolated_workspace(parent) as (child_ws, _sync_back):
            assert child_ws.name.startswith("subagent_ws_")
            assert child_ws.name.endswith("_my_project")


class TestSyncWorkspaceBackAsync:
    @pytest.mark.asyncio
    async def test_syncs_via_executor(self, tmp_path: Path):
        src = tmp_path / "src"
        src.mkdir()
        dst = tmp_path / "dst"
        dst.mkdir()

        (src / "file.txt").write_text("from_child")
        (dst / "old.txt").write_text("stale")

        await _sync_workspace_back(src, dst)

        assert (dst / "file.txt").read_text() == "from_child"
        assert not (dst / "old.txt").exists()


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

    @pytest.mark.asyncio
    async def test_propagates_clone_too_large_error(self, tmp_path: Path):
        src = tmp_path / "big_ws"
        src.mkdir()
        (src / "data.bin").write_bytes(b"\x00" * (2 * 1024 * 1024))

        with pytest.raises(WorkspaceCloneTooLargeError):
            async with isolated_workspace(src, max_bytes=1024 * 1024) as (_child_ws, _sync_back):
                pass

    @pytest.mark.asyncio
    async def test_accepts_string_path(self, parent_workspace: Path):
        async with isolated_workspace(str(parent_workspace)) as (child_ws, _sync_back):
            assert child_ws.exists()
            assert (child_ws / "file1.txt").read_text() == "hello"

    @pytest.mark.asyncio
    async def test_clone_skips_ignored_dirs(self, tmp_path: Path):
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "app.py").write_text("code")
        (ws / "node_modules").mkdir()
        (ws / "node_modules" / "pkg.js").write_text("heavy")

        async with isolated_workspace(ws) as (child_ws, _sync_back):
            assert (child_ws / "app.py").exists()
            assert not (child_ws / "node_modules").exists()
