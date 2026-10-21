from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.agent.goals.types import Goal
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

    with (
        patch("myrm_agent_harness.agent.goals.verification.VerificationGatekeeper") as mock_gatekeeper,
        patch(
            "myrm_agent_harness.agent.goals.finalizer.finalize_goal_complete",
            new_callable=AsyncMock,
        ) as mock_finalize,
    ):
        mock_gk_instance = AsyncMock()
        mock_gk_instance.verify_all.return_value = VerificationResult(passed=True)
        mock_gatekeeper.return_value = mock_gk_instance

        tools = create_goal_tools(mock_provider, "sess-1")
        complete_tool = tools[0]

        result = await complete_tool.ainvoke({})
        assert "Successfully marked goal" in result
        mock_finalize.assert_called_once()


@pytest.mark.asyncio
async def test_complete_goal_tool_idempotent_when_already_completed(mock_provider):
    from myrm_agent_harness.agent.goals.types import GoalStatus

    mock_goal = AsyncMock(spec=Goal)
    mock_goal.goal_id = "g-already-done"
    mock_goal.status = GoalStatus.COMPLETE
    mock_provider.get_active_goal.return_value = mock_goal

    tools = create_goal_tools(mock_provider, "sess-1")
    complete_tool = tools[0]

    result = await complete_tool.ainvoke({})
    assert "already completed" in result.lower()


@pytest.mark.asyncio
async def test_complete_goal_tool_with_criteria_fail(mock_provider):
    mock_goal = AsyncMock(spec=Goal)
    mock_goal.goal_id = "g-1"
    mock_goal.verification_retries = 0
    mock_goal.acceptance_criteria = [{"type": "shell", "command": "echo 1"}]
    mock_provider.get_active_goal.return_value = mock_goal

    from myrm_agent_harness.agent.goals.verification.base import AggregatedVerificationResult

    with patch("myrm_agent_harness.agent.goals.verification.VerificationGatekeeper") as mock_gatekeeper:
        mock_gk_instance = AsyncMock()
        single_res = VerificationResult(
            passed=False,
            criterion_label="Shell command 'echo 1'",
            reason="Bad command",
            error_logs="Not found",
        )
        mock_gk_instance.verify_all.return_value = AggregatedVerificationResult(
            passed=False,
            per_criterion=[single_res],
        )
        mock_gatekeeper.return_value = mock_gk_instance

        tools = create_goal_tools(mock_provider, "sess-1")
        complete_tool = tools[0]

        result = await complete_tool.ainvoke({})
        assert "Error: Verification failed (attempt 0/3)" in result
        assert "### Goal Verification Diagnostic Matrix" in result
        assert "| Shell command 'echo 1' | FAILED |" in result
        mock_provider.increment_verification_retries.assert_called_once_with("g-1")


@pytest.mark.asyncio
async def test_complete_goal_tool_with_criteria_max_retries(mock_provider):
    from myrm_agent_harness.agent.goals.types import GoalStatus
    from myrm_agent_harness.agent.goals.verification.base import AggregatedVerificationResult

    mock_goal = AsyncMock(spec=Goal)
    mock_goal.goal_id = "g-max"
    mock_goal.verification_retries = 3
    mock_goal.acceptance_criteria = [{"type": "shell", "command": "echo 1"}]
    mock_provider.get_active_goal.return_value = mock_goal

    with patch("myrm_agent_harness.agent.goals.verification.VerificationGatekeeper") as mock_gatekeeper:
        mock_gk_instance = AsyncMock()
        single_res = VerificationResult(
            passed=False,
            criterion_label="Shell Test",
            reason="Failed exit code 1",
            error_logs="Command failed",
        )
        mock_gk_instance.verify_all.return_value = AggregatedVerificationResult(
            passed=False,
            per_criterion=[single_res],
        )
        mock_gatekeeper.return_value = mock_gk_instance

        tools = create_goal_tools(mock_provider, "sess-1")
        complete_tool = tools[0]

        result = await complete_tool.ainvoke({})
        assert "Goal has been paused for human review" in result
        assert "### Goal Verification Diagnostic Matrix" in result
        assert "| Shell Test | FAILED |" in result
        mock_provider.update_status.assert_called_once_with("g-max", GoalStatus.NEEDS_HUMAN_REVIEW)


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


@pytest.mark.asyncio
async def test_complete_goal_tool_locale_descriptions(mock_provider):
    from myrm_agent_harness.agent.meta_tools.goals.goal_agent_tools import (
        COMPLETE_GOAL_TOOL_DESCRIPTION_EN,
        COMPLETE_GOAL_TOOL_DESCRIPTION_ZH,
        resolve_complete_goal_tool_description,
    )

    assert resolve_complete_goal_tool_description("en") == COMPLETE_GOAL_TOOL_DESCRIPTION_EN
    assert resolve_complete_goal_tool_description("zh-CN") == COMPLETE_GOAL_TOOL_DESCRIPTION_ZH
    assert resolve_complete_goal_tool_description(None) == COMPLETE_GOAL_TOOL_DESCRIPTION_EN

    zh_tools = create_goal_tools(mock_provider, "sess-1", locale="zh-CN")
    assert zh_tools[0].description == COMPLETE_GOAL_TOOL_DESCRIPTION_ZH

