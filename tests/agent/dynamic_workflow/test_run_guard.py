"""Tests for WorkflowRunGuard and spawn cap enforcement."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.agent.dynamic_workflow.tools import SpawnSubagentTool, WorkflowRunGuard


@pytest.mark.asyncio
async def test_run_guard_blocks_after_max_spawns():
    guard = WorkflowRunGuard(max_spawns=2, max_concurrent=5)
    parent = MagicMock()
    parent._spawn_child = AsyncMock(return_value={"success": True, "result": "ok"})
    parent._cached_tools = []
    parent.user_tools = []

    tool = SpawnSubagentTool(
        parent_agent=parent,
        tool_registry_getter=lambda: [],
        workflow_id="wf_cap",
        run_guard=guard,
    )

    first = await tool._arun("t1", "generalPurpose", "task one")
    second = await tool._arun("t2", "generalPurpose", "task two")
    third = await tool._arun("t3", "generalPurpose", "task three")

    assert first["success"] is True
    assert second["success"] is True
    assert third["success"] is False
    assert "spawn limit" in str(third["error"]).lower()
    assert parent._spawn_child.await_count == 2


@pytest.mark.asyncio
async def test_run_guard_semaphore_limits_concurrency():
    guard = WorkflowRunGuard(max_spawns=10, max_concurrent=1)
    parent = MagicMock()
    parent._cached_tools = []
    parent.user_tools = []

    entered = 0
    max_seen = 0
    lock = asyncio.Lock()

    async def slow_spawn(**kwargs: object) -> dict[str, object]:
        nonlocal entered, max_seen
        async with lock:
            entered += 1
            max_seen = max(max_seen, entered)
        await asyncio.sleep(0.05)
        async with lock:
            entered -= 1
        return {"success": True, "result": "ok"}

    parent._spawn_child = slow_spawn

    tool = SpawnSubagentTool(
        parent_agent=parent,
        tool_registry_getter=lambda: [],
        workflow_id="wf_sem",
        run_guard=guard,
    )

    await asyncio.gather(
        tool._arun("t1", "generalPurpose", "one"),
        tool._arun("t2", "generalPurpose", "two"),
    )

    assert max_seen == 1


def test_record_merge_candidate_dedupes_task_id():
    guard = WorkflowRunGuard()
    payload = {
        "success": True,
        "task_id": "task_a",
        "result": {
            "_isolated_child_workspace": "/tmp/child",
            "_isolated_parent_workspace": "/tmp/parent",
        },
    }
    guard.record_merge_candidate(payload)
    guard.record_merge_candidate(payload)
    assert len(guard.merge_results) == 1
