"""Tests for orchestrator.py — run_equivalence_refactor_wave."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.agent.sub_agents.orchestrator import (
    run_equivalence_refactor_wave,
)
from myrm_agent_harness.agent.sub_agents.types import (
    SubAgentResult,
    SubAgentStatus,
)


def _make_result(
    task_id: str,
    success: bool,
    status: SubAgentStatus = SubAgentStatus.COMPLETED,
    output: str = "Pruned 150 lines",
    error: str | None = None,
) -> SubAgentResult:
    return SubAgentResult(
        task_id=task_id,
        agent_type="worker",
        success=success,
        status=status,
        result=output,
        error=error,
        completed_at=time.time(),
    )


class TestEquivalenceRefactorWave:
    @pytest.mark.asyncio
    async def test_empty_tasks_returns_success(self) -> None:
        manager = MagicMock()
        res = await run_equivalence_refactor_wave(manager, [])
        assert res["success"] is True
        assert res["total_tasks"] == 0
        assert res["accepted_tasks"] == 0
        assert res["rejected_tasks"] == 0

    @pytest.mark.asyncio
    async def test_successful_refactor_wave(self) -> None:
        manager = MagicMock()
        manager.spawn_child = AsyncMock(side_effect=["task-1", "task-2"])
        manager.children = {}
        manager.child_results = {
            "task-1": _make_result("task-1", success=True, status=SubAgentStatus.COMPLETED, output="Pruned module A"),
            "task-2": _make_result("task-2", success=True, status=SubAgentStatus.COMPLETED, output="Pruned module B"),
        }

        tasks = [
            {"description": "Prune module A", "target_module": "core/a.py"},
            {"description": "Prune module B", "target_module": "core/b.py"},
        ]

        res = await run_equivalence_refactor_wave(manager, tasks)
        assert res["success"] is True
        assert res["total_tasks"] == 2
        assert res["accepted_tasks"] == 2
        assert res["rejected_tasks"] == 0
        assert len(res["accepted"]) == 2

    @pytest.mark.asyncio
    async def test_partial_failure_refactor_wave(self) -> None:
        manager = MagicMock()
        manager.spawn_child = AsyncMock(side_effect=["task-1", "task-2"])
        manager.children = {}
        manager.child_results = {
            "task-1": _make_result("task-1", success=True, status=SubAgentStatus.COMPLETED, output="Pruned A"),
            "task-2": _make_result("task-2", success=False, status=SubAgentStatus.FAILED, error="Regression test failed"),
        }

        tasks = [
            {"description": "Prune module A", "target_module": "core/a.py"},
            {"description": "Prune module B", "target_module": "core/b.py"},
        ]

        res = await run_equivalence_refactor_wave(manager, tasks)
        assert res["success"] is False
        assert res["total_tasks"] == 2
        assert res["accepted_tasks"] == 1
        assert res["rejected_tasks"] == 1
        assert len(res["rejected"]) == 1
        assert "Regression test failed" in str(res["rejected"][0]["error"])
