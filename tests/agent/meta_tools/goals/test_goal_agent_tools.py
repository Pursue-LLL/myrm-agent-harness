from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.agent.goals.types import Goal, GoalStatus
from myrm_agent_harness.agent.goals.verification.base import VerificationResult
from myrm_agent_harness.agent.meta_tools.goals.goal_agent_tools import create_goal_tools


@pytest.fixture
def mock_provider():
    provider = AsyncMock()
    provider.update_metadata = AsyncMock()
    return provider


@pytest.mark.asyncio
async def test_complete_goal_tool_named_correctly(mock_provider):
    tools = create_goal_tools(mock_provider, "sess-1")
    assert tools[0].name == "complete_goal_tool"


@pytest.mark.asyncio
async def test_complete_goal_tool_no_active_goal(mock_provider):
    mock_provider.get_active_goal.return_value = None
    tools = create_goal_tools(mock_provider, "sess-1")
    complete_tool = tools[0]

    result = await complete_tool.ainvoke({})
    assert "Error: No active goal to complete" in result


@pytest.mark.asyncio
async def test_complete_goal_tool_success_without_criteria(mock_provider):
    mock_goal = AsyncMock(spec=Goal)
    mock_goal.goal_id = "g-1"
    mock_goal.acceptance_criteria = []
    mock_provider.get_active_goal.return_value = mock_goal
    mock_provider.get_goal.return_value = mock_goal

    with patch(
        "myrm_agent_harness.agent.goals.finalizer.finalize_goal_complete",
        new_callable=AsyncMock,
    ) as mock_finalize:
        tools = create_goal_tools(mock_provider, "sess-1")
        complete_tool = tools[0]

        result = await complete_tool.ainvoke({})
        assert "Successfully marked goal" in result
        mock_finalize.assert_called_once()
        call_kwargs = mock_finalize.call_args.kwargs
        assert call_kwargs["source"] == "agent_tool"
        assert call_kwargs["defer_terminal_callback"] is True


@pytest.mark.asyncio
async def test_complete_goal_tool_with_criteria_pass(mock_provider):
    mock_goal = AsyncMock(spec=Goal)
    mock_goal.goal_id = "g-1"
    mock_goal.acceptance_criteria = [{"type": "shell", "command": "echo 1"}]
    mock_provider.get_active_goal.return_value = mock_goal

    with patch(
        "myrm_agent_harness.agent.goals.verification.VerificationGatekeeper"
    ) as MockGK, patch(
        "myrm_agent_harness.agent.goals.finalizer.finalize_goal_complete",
        new_callable=AsyncMock,
    ) as mock_finalize:
        mock_gk_instance = AsyncMock()
        mock_gk_instance.verify_all.return_value = VerificationResult(passed=True)
        MockGK.return_value = mock_gk_instance

        tools = create_goal_tools(mock_provider, "sess-1")
        complete_tool = tools[0]

        result = await complete_tool.ainvoke({})
        assert "Successfully marked goal" in result
        mock_finalize.assert_called_once()


@pytest.mark.asyncio
async def test_complete_goal_tool_with_criteria_fail(mock_provider):
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
        complete_tool = tools[0]

        result = await complete_tool.ainvoke({})
        assert "Error: Verification failed. You MUST fix this before completing" in result
        mock_provider.increment_verification_retries.assert_called_once_with("g-1")


@pytest.mark.asyncio
async def test_complete_goal_tool_exception(mock_provider):
    mock_goal = AsyncMock(spec=Goal)
    mock_goal.goal_id = "g-1"
    mock_goal.acceptance_criteria = []
    mock_provider.get_active_goal.return_value = mock_goal

    with patch(
        "myrm_agent_harness.agent.goals.finalizer.finalize_goal_complete",
        new_callable=AsyncMock,
        side_effect=Exception("DB error"),
    ):
        tools = create_goal_tools(mock_provider, "sess-1")
        complete_tool = tools[0]

        result = await complete_tool.ainvoke({})
        assert "Error completing goal: DB error" in result
