"""Tests for tool-initiated goal completion via deferred terminal resolution."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.agent.goals.finalizer import PENDING_TERMINAL_KEY
from myrm_agent_harness.agent.goals.types import Goal, GoalBudget, GoalStatus
from myrm_agent_harness.agent.goals.continuation import check_continuation


@pytest.mark.asyncio
async def test_check_continuation_resolves_deferred_tool_complete():
    provider = AsyncMock()
    goal = Goal(
        goal_id="tool-goal",
        session_id="sess-1",
        objective="Finish via tool",
        status=GoalStatus.COMPLETE,
        metadata={PENDING_TERMINAL_KEY: True},
        budget=GoalBudget(max_turns=10),
    )
    provider.get_active_goal.return_value = None
    provider.get_latest_goal.return_value = goal
    provider.update_metadata.return_value = goal

    decision = await check_continuation(
        goal_provider=provider,
        session_id="sess-1",
        cancel_token=None,
        steering_token=None,
        collected_messages=[],
        tools_called_this_turn=True,
        net_tokens_this_turn=0,
        cost_this_turn=0.0,
        time_this_turn_seconds=0,
    )

    assert decision.verdict == "done"
    assert decision.should_continue is False
    provider.update_metadata.assert_called_once()


@pytest.mark.asyncio
async def test_check_continuation_wait_skips_judge():
    provider = AsyncMock()
    goal = Goal(
        goal_id="wait-goal",
        session_id="sess-1",
        objective="Wait for CI",
        status=GoalStatus.WAIT,
        metadata={
            "wait_reason": "GitHub Actions running",
            "wait_started_at": "2099-01-01T00:00:00+00:00",
            "wait_max_seconds": 7200,
        },
    )
    provider.get_active_goal.return_value = None
    provider.get_latest_goal.return_value = goal

    decision = await check_continuation(
        goal_provider=provider,
        session_id="sess-1",
        cancel_token=None,
        steering_token=None,
        collected_messages=[],
        tools_called_this_turn=False,
        net_tokens_this_turn=0,
        cost_this_turn=0.0,
        time_this_turn_seconds=0,
    )

    assert decision.verdict == "wait"
    assert decision.should_continue is False
    provider.account_usage.assert_not_called()


@pytest.mark.asyncio
async def test_check_continuation_goal_focus_survives_compaction_prefix():
    """goal_focus middleware skips injection when continuation prefix is present."""
    from langchain_core.messages import HumanMessage

    from myrm_agent_harness.agent.middlewares.goal_focus_middleware import (
        _has_goal_continuation_prompt,
    )
    from myrm_agent_harness.agent.goals.goal_prompt_prefixes import GOAL_CONTINUATION_PREFIX

    messages = [HumanMessage(content=f"{GOAL_CONTINUATION_PREFIX}\nContinue working on the goal.")]
    assert _has_goal_continuation_prompt(messages) is True
