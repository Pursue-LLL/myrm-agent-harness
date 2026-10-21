"""Tournament winner merge must register revert snapshots."""

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
from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_batch import (
    _run_tournament_bracket,
)


@pytest.fixture(autouse=True)
def reset_snapshot_store() -> None:
    SnapshotStore.reset()
    yield
    SnapshotStore.reset()


@pytest.mark.asyncio
async def test_tournament_merge_registers_revert_snapshots(tmp_path: Path) -> None:
    parent = tmp_path / "parent"
    child = tmp_path / "child"
    parent.mkdir()
    child.mkdir()
    (child / "winner.txt").write_text("tournament winner", encoding="utf-8")

    set_current_message_id("msg_tournament")

    parent_agent = MagicMock()
    parent_agent._last_context = {
        "chat_id": "chat_tournament",
        "session_id": "chat_tournament",
        "workspace_path": str(parent),
    }

    winner = {
        "success": True,
        "task_id": "task_winner",
        "result": {
            "_isolated_child_workspace": str(child),
            "_isolated_parent_workspace": str(parent),
        },
    }

    payload = await _run_tournament_bracket(parent_agent, [winner], judge_criteria=None)

    assert payload.get("tournament_winner") is True
    assert payload.get("workspace_merge_ok") is True
    assert (parent / "winner.txt").is_file()

    changes = await RevertService.get_message_changes("chat_tournament", "msg_tournament")
    assert len(changes) == 1
    assert changes[0].path == "winner.txt"
    assert changes[0].operation == SnapshotOp.CREATE.value
