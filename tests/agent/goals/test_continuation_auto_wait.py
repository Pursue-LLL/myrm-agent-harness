"""Tests for auto WAIT when whitelisted background bash jobs are spawned."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.agent.goals.continuation import check_continuation
from myrm_agent_harness.agent.goals.types import Goal, GoalBudget, GoalStatus
from myrm_agent_harness.agent.middlewares.tool_interceptor_middleware import _loop_guard_var
from myrm_agent_harness.agent.security.guards.loop_guard import LoopGuard
from myrm_agent_harness.agent.security.guards.loop_guard_types import CallRecord


@pytest.mark.asyncio
async def test_check_continuation_auto_enters_wait_for_whitelisted_background_bash():
    provider = AsyncMock()
    goal = Goal(
        goal_id="wait-bg-goal",
        session_id="sess-1",
        objective="Run CI build",
        status=GoalStatus.ACTIVE,
        budget=GoalBudget(max_turns=10),
    )
    provider.get_active_goal.return_value = goal
    provider.get_goal.side_effect = [goal, goal]
    provider.account_usage.return_value = MagicMock(goal=goal, status_changed=False, budget_exhausted=False)
    provider.record_progress.return_value = goal
    provider.enter_wait.return_value = goal
    provider.update_metadata.return_value = goal

    guard = LoopGuard()
    guard._window.append(
        CallRecord(
            tool_name="bash_code_execute_tool",
            args_hash="h1",
            args={"command": "npm run build", "run_in_background": True},
            result_content="Background process started.\n  pid: 5555\n",
        )
    )
    token = _loop_guard_var.set(guard)
    try:
        decision = await check_continuation(
            goal_provider=provider,
            session_id="sess-1",
            cancel_token=None,
            steering_token=None,
            collected_messages=[],
            tools_called_this_turn=True,
            net_tokens_this_turn=100,
            cost_this_turn=0.01,
            time_this_turn_seconds=1,
        )
    finally:
        _loop_guard_var.reset(token)

    assert decision.verdict == "wait"
    assert decision.should_continue is False
    provider.enter_wait.assert_called_once()
    provider.update_metadata.assert_called_once()
