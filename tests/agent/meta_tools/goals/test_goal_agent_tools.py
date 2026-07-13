from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.agent.goals.types import Goal, GoalStatus
from myrm_agent_harness.agent.goals.verification.base import VerificationResult
from myrm_agent_harness.agent.meta_tools.goals.goal_agent_tools import create_goal_tools


@pytest.fixture
def mock_provider():
    provider = AsyncMock()
    return provider


@pytest.mark.asyncio
async def test_update_goal_status_invalid_status(mock_provider):
    tools = create_goal_tools(mock_provider, "sess-1")
    update_tool = tools[0]

    result = await update_tool.ainvoke({"status": "paused"})
    assert "Error: You can only update the status to 'complete'" in result


@pytest.mark.asyncio
async def test_update_goal_status_no_active_goal(mock_provider):
    mock_provider.get_active_goal.return_value = None
    tools = create_goal_tools(mock_provider, "sess-1")
    update_tool = tools[0]

    result = await update_tool.ainvoke({"status": "complete"})
    assert "Error: No active goal to update" in result


@pytest.mark.asyncio
async def test_update_goal_status_success_without_criteria(mock_provider):
    mock_goal = AsyncMock(spec=Goal)
    mock_goal.goal_id = "g-1"
    mock_goal.acceptance_criteria = []
    mock_provider.get_active_goal.return_value = mock_goal

    tools = create_goal_tools(mock_provider, "sess-1")
    update_tool = tools[0]

    result = await update_tool.ainvoke({"status": "complete"})
    assert "Successfully marked goal" in result
    mock_provider.update_status.assert_called_once_with("g-1", GoalStatus.COMPLETE)


@pytest.mark.asyncio
async def test_update_goal_status_with_criteria_pass(mock_provider):
    mock_goal = AsyncMock(spec=Goal)
    mock_goal.goal_id = "g-1"
    mock_goal.acceptance_criteria = [{"type": "shell", "command": "echo 1"}]
    mock_provider.get_active_goal.return_value = mock_goal

    with patch(
        "myrm_agent_harness.agent.goals.verification.VerificationGatekeeper"
    ) as MockGK:
        mock_gk_instance = AsyncMock()
        mock_gk_instance.verify_all.return_value = VerificationResult(passed=True)
        MockGK.return_value = mock_gk_instance

        tools = create_goal_tools(mock_provider, "sess-1")
        update_tool = tools[0]

        result = await update_tool.ainvoke({"status": "complete"})
        assert "Successfully marked goal" in result
        mock_provider.update_status.assert_called_once_with("g-1", GoalStatus.COMPLETE)


@pytest.mark.asyncio
async def test_update_goal_status_with_criteria_fail(mock_provider):
    mock_goal = AsyncMock(spec=Goal)
    mock_goal.goal_id = "g-1"
    mock_goal.verification_retries = 0
    mock_goal.acceptance_criteria = [{"type": "shell", "command": "echo 1"}]
    mock_provider.get_active_goal.return_value = mock_goal

    with patch(
        "myrm_agent_harness.agent.goals.verification.VerificationGatekeeper"
    ) as MockGK:
        mock_gk_instance = AsyncMock()
        mock_gk_instance.verify_all.return_value = VerificationResult(
            passed=False, reason="Bad command", error_logs="Not found"
        )
        MockGK.return_value = mock_gk_instance

        tools = create_goal_tools(mock_provider, "sess-1")
        update_tool = tools[0]

        result = await update_tool.ainvoke({"status": "complete"})
        assert (
            "Error: Verification failed. You MUST fix this before completing" in result
        )
        mock_provider.increment_verification_retries.assert_called_once_with("g-1")
        mock_provider.update_status.assert_not_called()


@pytest.mark.asyncio
async def test_update_goal_status_with_criteria_max_retries(mock_provider):
    mock_goal = AsyncMock(spec=Goal)
    mock_goal.goal_id = "g-1"
    mock_goal.verification_retries = 3
    mock_goal.acceptance_criteria = [{"type": "shell", "command": "echo 1"}]
    mock_provider.get_active_goal.return_value = mock_goal

    with patch(
        "myrm_agent_harness.agent.goals.verification.VerificationGatekeeper"
    ) as MockGK:
        mock_gk_instance = AsyncMock()
        mock_gk_instance.verify_all.return_value = VerificationResult(
            passed=False, reason="Bad command", error_logs="Not found"
        )
        MockGK.return_value = mock_gk_instance

        tools = create_goal_tools(mock_provider, "sess-1")
        update_tool = tools[0]

        result = await update_tool.ainvoke({"status": "complete"})
        assert "Goal has been paused for human review" in result
        mock_provider.update_status.assert_called_once_with(
            "g-1", GoalStatus.NEEDS_HUMAN_REVIEW
        )


@pytest.mark.asyncio
async def test_update_goal_status_exception(mock_provider):
    mock_goal = AsyncMock(spec=Goal)
    mock_goal.goal_id = "g-1"
    mock_goal.acceptance_criteria = []
    mock_provider.get_active_goal.return_value = mock_goal
    mock_provider.update_status.side_effect = Exception("DB error")

    tools = create_goal_tools(mock_provider, "sess-1")
    update_tool = tools[0]

    result = await update_tool.ainvoke({"status": "complete"})
    assert "Error updating goal: DB error" in result
