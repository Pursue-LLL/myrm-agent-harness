"""Tests for workspace isolation layer (Layer 1 of multi-agent state sync).

Verifies: COW clone, _sync_tree, _merge_tree_additive, size guards, cleanup.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

import pytest

from myrm_agent_harness.agent.sub_agents.workspace_isolation import (
    WorkspaceCloneTooLargeError,
    _clone_workspace,
    _merge_tree_additive,
    _sync_tree,
    isolated_workspace,
)


@pytest.fixture()
def parent_workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "parent"
    ws.mkdir()
    (ws / "plan.md").write_text("# Plan\n- Step 1\n- Step 2\n")
    (ws / "status.md").write_text("status: idle\n")
    sub = ws / "src"
    sub.mkdir()
    (sub / "main.py").write_text("print('hello')\n")
    return ws


class TestCloneWorkspace:
    def test_clone_copies_all_files(self, parent_workspace: Path, tmp_path: Path) -> None:
        dst = tmp_path / "child"
        count = _clone_workspace(parent_workspace, dst)
        assert count == 3
        assert (dst / "plan.md").read_text() == "# Plan\n- Step 1\n- Step 2\n"
        assert (dst / "src" / "main.py").read_text() == "print('hello')\n"

    def test_clone_ignores_node_modules(self, parent_workspace: Path, tmp_path: Path) -> None:
        (parent_workspace / "node_modules").mkdir()
        (parent_workspace / "node_modules" / "pkg.js").write_text("module.exports={}")
        dst = tmp_path / "child"
        count = _clone_workspace(parent_workspace, dst)
        assert count == 3
        assert not (dst / "node_modules").exists()

    def test_clone_ignores_git_dir(self, parent_workspace: Path, tmp_path: Path) -> None:
        (parent_workspace / ".git").mkdir()
        (parent_workspace / ".git" / "HEAD").write_text("ref: refs/heads/main")
        dst = tmp_path / "child"
        _clone_workspace(parent_workspace, dst)
        assert not (dst / ".git").exists()

    def test_clone_rejects_oversized_workspace(self, parent_workspace: Path, tmp_path: Path) -> None:
        dst = tmp_path / "child"
        with pytest.raises(WorkspaceCloneTooLargeError):
            _clone_workspace(parent_workspace, dst, max_bytes=10)


class TestSyncTree:
    def test_sync_additions(self, parent_workspace: Path, tmp_path: Path) -> None:
        dst = tmp_path / "child"
        _clone_workspace(parent_workspace, dst)
        (dst / "new_file.txt").write_text("new content")
        _sync_tree(dst, parent_workspace)
        assert (parent_workspace / "new_file.txt").read_text() == "new content"

    def test_sync_modifications(self, parent_workspace: Path, tmp_path: Path) -> None:
        dst = tmp_path / "child"
        _clone_workspace(parent_workspace, dst)
        (dst / "plan.md").write_text("# Updated Plan\n- Step 1 DONE\n")
        _sync_tree(dst, parent_workspace)
        assert "Updated Plan" in (parent_workspace / "plan.md").read_text()

    def test_sync_deletions(self, parent_workspace: Path, tmp_path: Path) -> None:
        dst = tmp_path / "child"
        _clone_workspace(parent_workspace, dst)
        (dst / "status.md").unlink()
        _sync_tree(dst, parent_workspace)
        assert not (parent_workspace / "status.md").exists()

    def test_sync_preserves_ignored_dirs(self, parent_workspace: Path, tmp_path: Path) -> None:
        (parent_workspace / ".git").mkdir()
        (parent_workspace / ".git" / "HEAD").write_text("ref: refs/heads/main")
        dst = tmp_path / "child"
        _clone_workspace(parent_workspace, dst)
        _sync_tree(dst, parent_workspace)
        assert (parent_workspace / ".git" / "HEAD").exists()


class TestMergeTreeAdditive:
    def test_additive_merge_adds_files(self, parent_workspace: Path, tmp_path: Path) -> None:
        child1 = tmp_path / "child1"
        _clone_workspace(parent_workspace, child1)
        (child1 / "result_a.txt").write_text("Agent A result")
        _merge_tree_additive(child1, parent_workspace)
        assert (parent_workspace / "result_a.txt").read_text() == "Agent A result"
        assert (parent_workspace / "plan.md").exists()

    def test_additive_merge_does_not_delete(self, parent_workspace: Path, tmp_path: Path) -> None:
        child1 = tmp_path / "child1"
        _clone_workspace(parent_workspace, child1)
        (child1 / "status.md").unlink()
        _merge_tree_additive(child1, parent_workspace)
        assert (parent_workspace / "status.md").exists()

    def test_additive_merge_updates_modified_files(self, parent_workspace: Path, tmp_path: Path) -> None:
        child1 = tmp_path / "child1"
        _clone_workspace(parent_workspace, child1)
        (child1 / "plan.md").write_text("# Updated by Agent A")
        _merge_tree_additive(child1, parent_workspace)
        assert "Agent A" in (parent_workspace / "plan.md").read_text()

    def test_parallel_agents_merge_sequentially(self, parent_workspace: Path, tmp_path: Path) -> None:
        child_a = tmp_path / "child_a"
        child_b = tmp_path / "child_b"
        _clone_workspace(parent_workspace, child_a)
        _clone_workspace(parent_workspace, child_b)
        (child_a / "agent_a_output.md").write_text("Output from Agent A")
        (child_b / "agent_b_output.md").write_text("Output from Agent B")
        _merge_tree_additive(child_a, parent_workspace)
        _merge_tree_additive(child_b, parent_workspace)
        assert (parent_workspace / "agent_a_output.md").exists()
        assert (parent_workspace / "agent_b_output.md").exists()
        assert (parent_workspace / "plan.md").exists()


class TestIsolatedWorkspaceContextManager:
    @pytest.mark.asyncio()
    async def test_context_manager_creates_and_cleans_up(self, parent_workspace: Path) -> None:
        child_path: Path | None = None
        async with isolated_workspace(parent_workspace) as (child_ws, sync_back):
            child_path = child_ws
            assert child_ws.exists()
            assert (child_ws / "plan.md").exists()
        assert not child_path.exists()

    @pytest.mark.asyncio()
    async def test_sync_back_works(self, parent_workspace: Path) -> None:
        async with isolated_workspace(parent_workspace) as (child_ws, sync_back):
            (child_ws / "child_output.txt").write_text("from child")
            await sync_back()
        assert (parent_workspace / "child_output.txt").read_text() == "from child"

    @pytest.mark.asyncio()
    async def test_no_sync_back_preserves_parent(self, parent_workspace: Path) -> None:
        async with isolated_workspace(parent_workspace) as (child_ws, _sync_back):
            (child_ws / "should_not_exist.txt").write_text("temporary")
        assert not (parent_workspace / "should_not_exist.txt").exists()
