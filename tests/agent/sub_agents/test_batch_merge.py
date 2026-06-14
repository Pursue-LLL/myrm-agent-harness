"""Tests for batch merge (Layer 3 of multi-agent state sync).

Verifies: sequential merge, error isolation, metadata cleanup.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.agent.sub_agents.workspace_isolation import (
    _clone_workspace,
    _merge_tree_additive,
)
from myrm_agent_harness.agent.workspace_coordination.batch_merge import (
    merge_batch_workspace_sync_backs,
)


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "base.txt").write_text("base content\n")
    return ws


class TestBatchMerge:
    @pytest.mark.asyncio()
    async def test_merge_with_sync_back_functions(self, workspace: Path, tmp_path: Path) -> None:
        child = tmp_path / "child"
        _clone_workspace(workspace, child)
        (child / "merged.txt").write_text("from sync_back")

        called = False

        async def fake_sync_back() -> None:
            nonlocal called
            _merge_tree_additive(child, workspace)
            called = True

        results: list[dict[str, object]] = [
            {
                "success": True,
                "result": {
                    "_workspace_sync_back": fake_sync_back,
                    "text": "done",
                },
            }
        ]
        summary = await merge_batch_workspace_sync_backs(results)
        assert summary["workspace_merge_ok"] is True
        assert summary["workspace_merge_merged_count"] == 1
        assert called

    @pytest.mark.asyncio()
    async def test_merge_skips_failed_tasks(self) -> None:
        results: list[dict[str, object]] = [
            {"success": False, "result": "error occurred"},
        ]
        summary = await merge_batch_workspace_sync_backs(results)
        assert summary["workspace_merge_merged_count"] == 0
        assert summary["workspace_merge_ok"] is True

    @pytest.mark.asyncio()
    async def test_merge_error_isolation(self, workspace: Path, tmp_path: Path) -> None:
        async def bad_sync_back() -> None:
            raise RuntimeError("merge failed")

        child = tmp_path / "child2"
        _clone_workspace(workspace, child)
        (child / "good.txt").write_text("good")

        async def good_sync_back() -> None:
            _merge_tree_additive(child, workspace)

        results: list[dict[str, object]] = [
            {
                "success": True,
                "result": {"_workspace_sync_back": bad_sync_back, "text": "bad"},
            },
            {
                "success": True,
                "result": {"_workspace_sync_back": good_sync_back, "text": "good"},
            },
        ]
        summary = await merge_batch_workspace_sync_backs(results)
        assert summary["workspace_merge_merged_count"] == 1
        assert len(summary["workspace_merge_errors"]) == 1

    @pytest.mark.asyncio()
    async def test_merge_with_isolated_child_workspace(self, workspace: Path, tmp_path: Path) -> None:
        child = tmp_path / "iso_child"
        _clone_workspace(workspace, child)
        (child / "from_iso.txt").write_text("isolated result")

        results: list[dict[str, object]] = [
            {
                "success": True,
                "result": {
                    "_isolated_child_workspace": str(child),
                    "_isolated_parent_workspace": str(workspace),
                    "text": "done",
                },
            }
        ]
        summary = await merge_batch_workspace_sync_backs(results)
        assert summary["workspace_merge_ok"] is True
        assert summary["workspace_merge_merged_count"] == 1
        assert (workspace / "from_iso.txt").read_text() == "isolated result"

    @pytest.mark.asyncio()
    async def test_metadata_cleanup_after_merge(self) -> None:
        async def noop_sync() -> None:
            pass

        results: list[dict[str, object]] = [
            {
                "success": True,
                "result": {
                    "_workspace_sync_back": noop_sync,
                    "_isolated_child_workspace": "/tmp/fake",
                    "_isolated_parent_workspace": "/tmp/fake_parent",
                    "useful_data": "keep me",
                },
            }
        ]
        await merge_batch_workspace_sync_backs(results)
        inner = results[0]["result"]
        assert isinstance(inner, dict)
        assert "_workspace_sync_back" not in inner
        assert "_isolated_child_workspace" not in inner
        assert inner.get("useful_data") == "keep me"
