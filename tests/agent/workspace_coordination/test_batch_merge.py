"""Tests for parallel batch workspace merge."""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.agent.sub_agents.workspace_isolation import _clone_workspace
from myrm_agent_harness.agent.workspace_coordination.batch_merge import (
    merge_batch_workspace_sync_backs,
)
from myrm_agent_harness.agent.workspace_coordination.policy import (
    apply_parallel_write_isolation,
    count_parallel_writers,
)
from myrm_agent_harness.agent.sub_agents.types import SubagentConfig, WorkspacePolicy


@pytest.mark.asyncio
async def test_merge_batch_workspace_sync_backs_applies_changes(tmp_path: Path) -> None:
    parent = tmp_path / "parent"
    parent.mkdir()
    (parent / "base.txt").write_text("base", encoding="utf-8")

    child_a = tmp_path / "child_a"
    child_b = tmp_path / "child_b"
    child_a.mkdir()
    child_b.mkdir()
    _clone_workspace(parent, child_a)
    _clone_workspace(parent, child_b)
    (child_a / "from_a.txt").write_text("a", encoding="utf-8")
    (child_b / "from_b.txt").write_text("b", encoding="utf-8")

    results = [
        {
            "success": True,
            "result": {
                "_isolated_child_workspace": str(child_a),
                "_isolated_parent_workspace": str(parent),
            },
        },
        {
            "success": True,
            "result": {
                "_isolated_child_workspace": str(child_b),
                "_isolated_parent_workspace": str(parent),
            },
        },
    ]
    summary = await merge_batch_workspace_sync_backs(results)

    assert summary["workspace_merge_ok"] is True
    assert summary["workspace_merge_merged_count"] == 2
    assert (parent / "from_a.txt").read_text(encoding="utf-8") == "a"
    assert (parent / "from_b.txt").read_text(encoding="utf-8") == "b"


def test_apply_parallel_write_isolation_promotes_isolated_copy() -> None:
    config = SubagentConfig(system_prompt="test")
    assert config.workspace_policy == WorkspacePolicy.INHERIT

    updated_config, updated_context = apply_parallel_write_isolation(
        config=config,
        child_context={"workspace_path": "/tmp/ws"},
        readonly=False,
        parallel_write_batch=True,
    )

    assert updated_config.workspace_policy == WorkspacePolicy.ISOLATED_COPY
    assert updated_context["_defer_workspace_merge"] is True


def test_count_parallel_writers() -> None:
    class _Task:
        def __init__(self, readonly: bool) -> None:
            self.readonly = readonly

    tasks = [_Task(False), _Task(True), _Task(False)]
    assert count_parallel_writers(tasks) == 2
