"""Runner batch merge must register revert snapshots (G1)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from myrm_agent_harness.agent.meta_tools.file_ops.observers.snapshot_observer import (
    SnapshotOp,
    SnapshotStore,
    set_current_message_id,
)
from myrm_agent_harness.agent.meta_tools.file_ops.revert_service import RevertService
from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import (
    TaskRequest,
)
from myrm_agent_harness.agent.parallel.runner import run_parallel_task_requests


@pytest.fixture(autouse=True)
def reset_snapshot_store() -> None:
    SnapshotStore.reset()
    yield
    SnapshotStore.reset()


@pytest.mark.asyncio
async def test_runner_parallel_merge_registers_revert_snapshots(tmp_path: Path) -> None:
    parent = tmp_path / "parent"
    child_a = tmp_path / "child_a"
    child_b = tmp_path / "child_b"
    parent.mkdir()
    child_a.mkdir()
    child_b.mkdir()
    (child_a / "a.csv").write_text("a\n", encoding="utf-8")
    (child_b / "b.csv").write_text("b\n", encoding="utf-8")

    set_current_message_id("msg_runner")

    parent_agent = MagicMock()
    parent_agent._last_context = {
        "chat_id": "chat_runner",
        "session_id": "chat_runner",
        "workspace_path": str(parent),
    }

    async def _delegate_coroutine(**kwargs: object) -> dict[str, object]:
        agent_type = str(kwargs.get("agent_type", ""))
        child = child_a if agent_type == "a" else child_b
        return {
            "success": True,
            "agent_type": agent_type,
            "task_id": f"task-{agent_type}",
            "result": {
                "_isolated_child_workspace": str(child),
                "_isolated_parent_workspace": str(parent),
            },
        }

    delegate_tool = MagicMock()
    delegate_tool.coroutine = _delegate_coroutine

    tasks = [
        TaskRequest(agent_type="a", objective="write a"),
        TaskRequest(agent_type="b", objective="write b"),
    ]

    result = await run_parallel_task_requests(
        parent_agent=parent_agent,
        delegate_tool=delegate_tool,
        tasks=tasks,
        wait=True,
        race=False,
    )

    assert result.get("workspace_merge_ok") is True
    assert (parent / "a.csv").is_file()
    assert (parent / "b.csv").is_file()

    changes = await RevertService.get_message_changes("chat_runner", "msg_runner")
    assert len(changes) == 2
    paths = {change.path for change in changes}
    assert paths == {"a.csv", "b.csv"}
    assert all(change.operation == SnapshotOp.CREATE.value for change in changes)


@pytest.mark.asyncio
async def test_race_merge_registers_revert_snapshots(tmp_path: Path) -> None:
    parent = tmp_path / "parent"
    child = tmp_path / "child_slow"
    child_fast = tmp_path / "child_fast"
    parent.mkdir()
    child.mkdir()
    child_fast.mkdir()
    (child_fast / "winner.md").write_text("race winner\n", encoding="utf-8")

    set_current_message_id("msg_race")

    parent_agent = MagicMock()
    parent_agent._last_context = {
        "chat_id": "chat_race",
        "session_id": "chat_race",
        "workspace_path": str(parent),
    }

    async def _delegate_coroutine(**kwargs: object) -> dict[str, object]:
        objective = str(kwargs.get("objective", ""))
        if "slow" in objective:
            await asyncio.sleep(0.2)
            return {
                "success": True,
                "task_id": "slow",
                "result": {
                    "_isolated_child_workspace": str(child),
                    "_isolated_parent_workspace": str(parent),
                },
            }
        return {
            "success": True,
            "task_id": "fast",
            "result": {
                "_isolated_child_workspace": str(child_fast),
                "_isolated_parent_workspace": str(parent),
            },
        }

    delegate_tool = MagicMock()
    delegate_tool.coroutine = _delegate_coroutine

    tasks = [
        TaskRequest(agent_type="a", objective="slow task"),
        TaskRequest(agent_type="b", objective="fast task"),
    ]

    result = await run_parallel_task_requests(
        parent_agent=parent_agent,
        delegate_tool=delegate_tool,
        tasks=tasks,
        wait=True,
        race=True,
    )

    assert result.get("race_winner") is True
    assert result.get("workspace_merge_ok") is True
    assert (parent / "winner.md").is_file()

    changes = await RevertService.get_message_changes("chat_race", "msg_race")
    assert len(changes) == 1
    assert changes[0].path == "winner.md"
