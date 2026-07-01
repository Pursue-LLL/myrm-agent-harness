"""Tests for code_graph lifecycle — workspace isolation, TTL cleanup, custom parsers."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.code_graph.lifecycle import (
    CodeGraphLifecycle,
    WorkspaceInfo,
    _workspace_hash,
)


@pytest.fixture
def lifecycle(tmp_path: Path) -> CodeGraphLifecycle:
    return CodeGraphLifecycle(tmp_path)


class TestWorkspaceHash:
    def test_deterministic(self) -> None:
        h1 = _workspace_hash("/home/user/project")
        h2 = _workspace_hash("/home/user/project")
        assert h1 == h2

    def test_different_paths_different_hashes(self) -> None:
        h1 = _workspace_hash("/home/user/project-a")
        h2 = _workspace_hash("/home/user/project-b")
        assert h1 != h2

    def test_hash_length_is_16(self) -> None:
        h = _workspace_hash("/any/path")
        assert len(h) == 16


class TestEnsureDirectory:
    def test_creates_code_graph_dir(self, lifecycle: CodeGraphLifecycle, tmp_path: Path) -> None:
        graph_dir = lifecycle.ensure_directory()
        assert graph_dir.exists()
        assert graph_dir.name == "code_graph"

    def test_idempotent(self, lifecycle: CodeGraphLifecycle) -> None:
        d1 = lifecycle.ensure_directory()
        d2 = lifecycle.ensure_directory()
        assert d1 == d2


class TestGetWorkspaceInfo:
    def test_nonexistent_workspace(self, lifecycle: CodeGraphLifecycle) -> None:
        info = lifecycle.get_workspace_info("/nonexistent/path")
        assert isinstance(info, WorkspaceInfo)
        assert info.exists is False
        assert info.size_bytes == 0

    def test_existing_workspace(self, lifecycle: CodeGraphLifecycle, tmp_path: Path) -> None:
        store = lifecycle.open_store("/test/workspace")
        store.close()

        info = lifecycle.get_workspace_info("/test/workspace")
        assert info.exists is True
        assert info.size_bytes > 0
        assert info.workspace_hash == _workspace_hash("/test/workspace")


class TestOpenStore:
    def test_creates_and_opens_store(self, lifecycle: CodeGraphLifecycle) -> None:
        store = lifecycle.open_store("/test/workspace")
        assert store.node_count() == 0
        store.close()

    def test_opens_existing_store(self, lifecycle: CodeGraphLifecycle) -> None:
        store1 = lifecycle.open_store("/test/workspace")
        store1.close()

        store2 = lifecycle.open_store("/test/workspace")
        assert store2.node_count() == 0
        store2.close()

    def test_loads_custom_parsers_if_exists(
        self, lifecycle: CodeGraphLifecycle, tmp_path: Path,
    ) -> None:
        ws_root = tmp_path / "workspace_with_config"
        ws_root.mkdir()
        (ws_root / "languages.toml").write_text(
            '[languages.elixir]\n'
            'extensions = [".ex", ".exs"]\n'
            'tree_sitter_language = "elixir"\n'
        )

        store = lifecycle.open_store(str(ws_root))
        store.close()


class TestListWorkspaces:
    def test_empty_when_no_databases(self, lifecycle: CodeGraphLifecycle) -> None:
        assert lifecycle.list_workspaces() == []

    def test_lists_created_workspaces(self, lifecycle: CodeGraphLifecycle) -> None:
        store1 = lifecycle.open_store("/workspace/a")
        store1.close()
        store2 = lifecycle.open_store("/workspace/b")
        store2.close()

        workspaces = lifecycle.list_workspaces()
        assert len(workspaces) >= 2
        assert all(ws.exists for ws in workspaces)


class TestCleanupStale:
    def test_no_cleanup_when_recent(self, lifecycle: CodeGraphLifecycle) -> None:
        store = lifecycle.open_store("/test/workspace")
        store.close()

        removed = lifecycle.cleanup_stale(ttl_days=30)
        assert removed == 0

    def test_cleanup_old_databases(self, lifecycle: CodeGraphLifecycle) -> None:
        store = lifecycle.open_store("/test/old-workspace")
        store.close()

        info = lifecycle.get_workspace_info("/test/old-workspace")
        old_time = time.time() - (60 * 86400)
        import os
        os.utime(str(info.db_path), (old_time, old_time))

        removed = lifecycle.cleanup_stale(ttl_days=30)
        assert removed == 1

    def test_no_cleanup_when_empty(self, lifecycle: CodeGraphLifecycle) -> None:
        removed = lifecycle.cleanup_stale()
        assert removed == 0


class TestDeleteWorkspace:
    def test_delete_existing(self, lifecycle: CodeGraphLifecycle) -> None:
        store = lifecycle.open_store("/test/workspace")
        store.close()

        assert lifecycle.delete_workspace("/test/workspace") is True
        info = lifecycle.get_workspace_info("/test/workspace")
        assert info.exists is False

    def test_delete_nonexistent(self, lifecycle: CodeGraphLifecycle) -> None:
        assert lifecycle.delete_workspace("/nonexistent") is False


class TestTotalSize:
    def test_zero_when_no_databases(self, lifecycle: CodeGraphLifecycle) -> None:
        assert lifecycle.total_size_bytes() == 0

    def test_nonzero_after_creating_store(self, lifecycle: CodeGraphLifecycle) -> None:
        store = lifecycle.open_store("/test/workspace")
        store.close()

        assert lifecycle.total_size_bytes() > 0
