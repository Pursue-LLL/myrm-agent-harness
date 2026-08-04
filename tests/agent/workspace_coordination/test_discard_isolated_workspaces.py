"""Tests for discarding deferred ISOLATED_COPY workspaces without merge."""

from __future__ import annotations

from pathlib import Path

from myrm_agent_harness.agent.sub_agents.types import (
    SubAgentResult,
    SubAgentStatus,
)
from myrm_agent_harness.agent.workspace_coordination.batch_merge import (
    discard_deferred_isolated_workspaces,
)


def test_discard_deferred_isolated_workspaces_removes_child_and_metadata(
    tmp_path: Path,
) -> None:
    child = tmp_path / "child"
    child.mkdir()
    (child / "note.txt").write_text("x", encoding="utf-8")

    result = SubAgentResult(
        success=True,
        task_id="alt-1",
        agent_type="worker",
        result={
            "text": "answer",
            "_isolated_child_workspace": str(child),
            "_isolated_parent_workspace": str(tmp_path / "parent"),
            "_workspace_sync_back": lambda: None,
        },
        status=SubAgentStatus.COMPLETED,
        completed_at=0.0,
    )

    removed = discard_deferred_isolated_workspaces([result])

    assert removed == 1
    assert not child.exists()
    assert isinstance(result.result, dict)
    assert result.result == {"text": "answer"}


def test_discard_cleans_failed_alternative_child_workspace(tmp_path: Path) -> None:
    child = tmp_path / "failed_child"
    child.mkdir()

    result = SubAgentResult(
        success=False,
        task_id="alt-fail",
        agent_type="worker",
        result={
            "text": "",
            "_isolated_child_workspace": str(child),
            "_isolated_parent_workspace": str(tmp_path / "parent"),
            "_workspace_sync_back": lambda: None,
        },
        error="failed",
        status=SubAgentStatus.FAILED,
        completed_at=0.0,
    )

    removed = discard_deferred_isolated_workspaces([result])

    assert removed == 1
    assert not child.exists()
    assert isinstance(result.result, dict)
    assert result.result == {"text": ""}
