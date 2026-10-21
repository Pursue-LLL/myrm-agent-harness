from unittest.mock import MagicMock

import pytest

from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import (
    TaskRequest,
)
from myrm_agent_harness.agent.parallel.runner import run_parallel_task_requests


@pytest.mark.asyncio
async def test_run_parallel_task_requests_preserves_agent_type() -> None:
    parent_agent = MagicMock()
    captured_agent_types: list[str] = []

    async def _delegate_coroutine(**kwargs: object) -> dict[str, object]:
        agent_type = str(kwargs.get("agent_type", ""))
        captured_agent_types.append(agent_type)
        return {
            "success": True,
            "agent_type": agent_type,
            "result": f"done:{agent_type}",
            "task_id": f"task-{agent_type}",
        }

    delegate_tool = MagicMock()
    delegate_tool.coroutine = _delegate_coroutine

    tasks = [
        TaskRequest(agent_type="research", objective="Research A"),
        TaskRequest(agent_type="code", objective="Review B"),
    ]

    result = await run_parallel_task_requests(
        parent_agent=parent_agent,
        delegate_tool=delegate_tool,
        tasks=tasks,
        wait=True,
        race=False,
        max_concurrent=2,
    )

    assert result["success"] is True
    assert captured_agent_types == ["research", "code"]
    raw_results = result.get("results")
    assert isinstance(raw_results, list)
    assert len(raw_results) == 2
    assert raw_results[0]["agent_type"] == "research"
    assert raw_results[1]["agent_type"] == "code"


@pytest.mark.asyncio
async def test_run_parallel_race_activates_write_isolation() -> None:
    """Ensure race execution activates _parallel_write_batch_active when tasks are writers."""
    parent_agent = MagicMock()
    parent_agent._parallel_write_batch_active = None
    observed_active_states: list[bool] = []

    async def _delegate_coroutine(**kwargs: object) -> dict[str, object]:
        agent_type = str(kwargs.get("agent_type", ""))
        observed_active_states.append(getattr(parent_agent, "_parallel_write_batch_active", False))
        return {
            "success": True,
            "agent_type": agent_type,
            "result": f"done:{agent_type}",
            "task_id": f"task-{agent_type}",
        }

    delegate_tool = MagicMock()
    delegate_tool.coroutine = _delegate_coroutine

    tasks = [
        TaskRequest(agent_type="code_a", objective="Implement A", readonly=False),
        TaskRequest(agent_type="code_b", objective="Implement B", readonly=False),
    ]

    result = await run_parallel_task_requests(
        parent_agent=parent_agent,
        delegate_tool=delegate_tool,
        tasks=tasks,
        wait=True,
        race=True,
        max_concurrent=2,
    )

    assert result["success"] is True
    assert result.get("race_winner") is True
    # Verify that while subtasks ran, write isolation flag was active
    assert any(observed_active_states) is True
    # Verify clean-up of attribute on parent
    assert not hasattr(parent_agent, "_parallel_write_batch_active") or parent_agent._parallel_write_batch_active is None

