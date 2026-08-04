"""Tests for merge-time revert snapshot registration."""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.agent.meta_tools.file_ops.observers.snapshot_observer import (
    SnapshotOp,
    SnapshotStore,
)
from myrm_agent_harness.agent.meta_tools.file_ops.revert_service import RevertService
from myrm_agent_harness.agent.workspace_coordination.batch_merge import (
    merge_batch_workspace_sync_backs,
)
from myrm_agent_harness.agent.workspace_coordination.merge_snapshots import (
    MergeSnapshotContext,
    apply_isolated_sync_back_with_snapshots,
    build_merge_snapshot_context,
)


@pytest.fixture(autouse=True)
def reset_snapshot_store() -> None:
    SnapshotStore.reset()
    yield
    SnapshotStore.reset()


@pytest.mark.asyncio
async def test_batch_merge_registers_revert_snapshots(tmp_path: Path) -> None:
    parent = tmp_path / "parent"
    child = tmp_path / "child"
    parent.mkdir()
    child.mkdir()
    (child / "report.csv").write_text("a,b,c\n", encoding="utf-8")

    ctx = MergeSnapshotContext(
        session_id="chat_1",
        message_id="msg_1",
        workspace_root=str(parent),
    )
    results: list[dict[str, object]] = [
        {
            "success": True,
            "task_id": "task_a",
            "result": {
                "_isolated_child_workspace": str(child),
                "_isolated_parent_workspace": str(parent),
            },
        }
    ]

    summary = await merge_batch_workspace_sync_backs(results, snapshot_context=ctx)
    assert summary["workspace_merge_ok"] is True
    assert (parent / "report.csv").is_file()

    changes = await RevertService.get_message_changes("chat_1", "msg_1")
    assert len(changes) == 1
    assert changes[0].path == "report.csv"
    assert changes[0].operation == SnapshotOp.CREATE.value


def test_build_merge_snapshot_context_explicit_ids() -> None:
    ctx = build_merge_snapshot_context(
        session_id="chat_x",
        message_id="msg_y",
        workspace_root="/ws",
    )
    assert ctx == MergeSnapshotContext(
        session_id="chat_x",
        message_id="msg_y",
        workspace_root="/ws",
    )


def test_build_merge_snapshot_context_prefers_parent_chat_id() -> None:
    parent_agent = type("Agent", (), {"_last_context": {"chat_id": "raw_chat", "session_id": "chat_raw_chat"}})()
    ctx = build_merge_snapshot_context(
        message_id="msg_1",
        workspace_root="/ws",
        parent_agent=parent_agent,
    )
    assert ctx is not None
    assert ctx.session_id == "raw_chat"


def test_build_merge_snapshot_context_missing_message_returns_none() -> None:
    assert build_merge_snapshot_context(session_id="chat_x") is None


@pytest.mark.asyncio
async def test_apply_isolated_sync_back_registers_revert_snapshots(tmp_path: Path) -> None:
    from unittest.mock import MagicMock

    from myrm_agent_harness.agent.meta_tools.file_ops.observers.snapshot_observer import (
        set_current_message_id,
    )
    from myrm_agent_harness.agent.sub_agents.workspace_isolation import isolated_workspace

    parent = tmp_path / "parent"
    parent.mkdir()
    set_current_message_id("msg_sync")

    parent_agent = MagicMock()
    parent_agent._last_context = {
        "chat_id": "chat_sync",
        "workspace_path": str(parent),
    }

    async with isolated_workspace(parent) as (child, sync_back):
        (child / "analysis.md").write_text("# analysis\n", encoding="utf-8")
        await apply_isolated_sync_back_with_snapshots(
            child_workspace=child,
            parent_workspace=parent,
            sync_back=sync_back,
            parent_agent=parent_agent,
        )

    assert (parent / "analysis.md").is_file()
    changes = await RevertService.get_message_changes("chat_sync", "msg_sync")
    assert len(changes) == 1
    assert changes[0].path == "analysis.md"
    assert changes[0].operation == SnapshotOp.CREATE.value
