from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.sub_agents.orchestrator import execute_dag_plan
from myrm_agent_harness.agent.sub_agents.planner.schemas import Plan, PlanStep
from myrm_agent_harness.agent.sub_agents.types import SubAgentResult, SubAgentStatus


@pytest.mark.asyncio
async def test_swarm_fission_yield_resume_via_parallel_runner() -> None:
    plan = Plan(
        goal="Test Swarm Fission",
        reasoning="Testing",
        steps=[
            PlanStep(
                step_id="step_1",
                description="Main task",
                expected_output="Final report",
                status="pending",
            )
        ],
    )

    manager = MagicMock()
    manager._parent_agent = MagicMock()

    fission_resume = {
        "success": True,
        "status": "completed",
        "total_count": 2,
        "completed_count": 2,
        "failed_count": 0,
        "results": [
            {
                "task_index": 0,
                "agent_type": "research",
                "success": True,
                "result": "Result 1",
            },
            {
                "task_index": 1,
                "agent_type": "research",
                "success": True,
                "result": "Result 2",
            },
        ],
    }

    yield_result = SubAgentResult(
        success=True,
        task_id="dag-step_1",
        agent_type="general",
        status=SubAgentStatus.YIELDED,
        payload={
            "action_type": "swarm_fission",
            "tasks": [
                {"agent_type": "research", "objective": "Sub 1"},
                {"agent_type": "research", "objective": "Sub 2"},
            ],
        },
        checkpoint_data={"thread_id": "dag-step_1"},
    )

    final_result = SubAgentResult(
        success=True,
        task_id="dag-step_1",
        agent_type="general",
        result="Final Report",
        status=SubAgentStatus.COMPLETED,
    )

    async def mock_spawn_child(*args, **kwargs):
        task_id = kwargs.get("task_id")
        resume_cmd = kwargs.get("resume_command")
        if task_id == "dag-step_1" and resume_cmd is None:
            return yield_result
        if task_id == "dag-step_1" and resume_cmd is not None:
            assert resume_cmd.resume == fission_resume
            return final_result
        raise ValueError(f"Unexpected call: {task_id}, {resume_cmd}")

    manager.spawn_child = AsyncMock(side_effect=mock_spawn_child)

    with patch(
        "myrm_agent_harness.agent.parallel.fission.execute_swarm_fission",
        new=AsyncMock(return_value=fission_resume),
    ), patch(
        "myrm_agent_harness.agent.artifacts.vault.ArtifactVault.get_instance",
        create=True,
    ):
        result = await execute_dag_plan(
            plan=plan,
            manager=manager,
            context={},
            tool_registry_getter=lambda: [],
        )

    assert result["success"] is True
    assert len(plan.steps) == 1
    assert plan.steps[0].status == "completed"
