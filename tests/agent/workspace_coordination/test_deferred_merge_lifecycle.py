"""Integration tests for deferred ISOLATED_COPY merge lifecycle."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from myrm_agent_harness.agent.sub_agents.spawn_prep import (
    merge_candidate_from_spawn_dict,
    sanitize_spawn_result_for_store,
    spawn_result_for_store_after_merge,
)
from myrm_agent_harness.agent.sub_agents.workspace_isolation import isolated_workspace
from myrm_agent_harness.agent.workspace_coordination.batch_merge import (
    merge_batch_workspace_sync_backs,
)


@pytest.mark.asyncio
async def test_deferred_isolated_workspace_survives_until_batch_merge(tmp_path: Path) -> None:
    """Child workspace must remain until batch_merge merges and cleans up."""
    parent = tmp_path / "parent"
    parent.mkdir()
    cleanup_policy = {"on_exit": False}
    child_ws: Path

    async with isolated_workspace(parent, cleanup_policy=cleanup_policy) as (child, _sync_back):
        child_ws = child
        (child / "deliverable.md").write_text("merged content", encoding="utf-8")

    assert child_ws.is_dir(), "defer cleanup must keep child workspace for batch_merge"

    results: list[dict[str, object]] = [
        {
            "success": True,
            "task_id": "task_a",
            "result": {
                "_isolated_child_workspace": str(child_ws),
                "_isolated_parent_workspace": str(parent),
            },
        }
    ]
    summary = await merge_batch_workspace_sync_backs(results)
    assert summary["workspace_merge_ok"] is True
    assert summary["workspace_merge_merged_count"] == 1
    assert (parent / "deliverable.md").read_text(encoding="utf-8") == "merged content"
    assert not child_ws.is_dir()


@pytest.mark.asyncio
async def test_missing_child_workspace_fails_loud() -> None:
    results: list[dict[str, object]] = [
        {
            "success": True,
            "task_id": "ghost",
            "result": {
                "_isolated_child_workspace": "/tmp/nonexistent_child_ws",
                "_isolated_parent_workspace": "/tmp/nonexistent_parent_ws",
            },
        }
    ]
    summary = await merge_batch_workspace_sync_backs(results)
    assert summary["workspace_merge_ok"] is False
    assert summary["workspace_merge_merged_count"] == 0
    assert summary["workspace_merge_errors"]

    from myrm_agent_harness.agent.workspace_coordination.merge_warning import (
        has_workspace_merge_warning,
        reset_workspace_merge_warning,
    )

    reset_workspace_merge_warning()
    await merge_batch_workspace_sync_backs(results)
    assert has_workspace_merge_warning() is True


def test_sanitize_spawn_result_for_store_strips_callables() -> None:
    def sync_back() -> None:
        return None

    raw: dict[str, object] = {
        "success": True,
        "task_id": "t1",
        "result": {
            "text": "ok",
            "_workspace_sync_back": sync_back,
            "_isolated_child_workspace": "/tmp/child",
            "_isolated_parent_workspace": "/tmp/parent",
        },
    }
    stored = sanitize_spawn_result_for_store(raw)
    json.dumps(stored)
    assert not merge_candidate_from_spawn_dict(stored)
    assert stored.get("workspace_merge_status") == "pending"
    inner = stored["result"]
    assert isinstance(inner, dict)
    assert "_workspace_sync_back" not in inner


def test_spawn_result_for_store_after_merge_marks_merged() -> None:
    merged_item: dict[str, object] = {
        "success": True,
        "task_id": "t1",
        "workspace_merge_status": "merged",
        "result": {"text": "ok"},
    }
    stored = spawn_result_for_store_after_merge(merged_item)
    assert stored["workspace_merge_status"] == "merged"
