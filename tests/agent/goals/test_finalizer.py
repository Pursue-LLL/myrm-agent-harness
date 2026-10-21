"""Tests for GoalFinalizer SSOT completion path."""

from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.agent.goals.finalizer import (
    PENDING_TERMINAL_KEY,
    finalize_goal_complete,
    resolve_deferred_tool_completion,
)
from myrm_agent_harness.agent.goals.types import Goal, GoalStatus


@pytest.fixture
def mock_provider():
    provider = AsyncMock()
    provider.update_metadata = AsyncMock()
    return provider


def _goal(status: GoalStatus = GoalStatus.ACTIVE) -> Goal:
    return Goal(
        goal_id="g-1",
        session_id="sess-1",
        objective="Test objective",
        status=status,
    )


@pytest.mark.asyncio
async def test_finalize_goal_complete_idempotent(mock_provider):
    complete_goal = _goal(GoalStatus.COMPLETE)
    mock_provider.get_goal.return_value = complete_goal

    result = await finalize_goal_complete(mock_provider, complete_goal, source="semantic_judge")
    assert result.status == GoalStatus.COMPLETE
    mock_provider.update_status.assert_not_called()


@pytest.mark.asyncio
async def test_finalize_goal_complete_sets_pending_for_tool(mock_provider):
    active = _goal(GoalStatus.ACTIVE)
    completed = _goal(GoalStatus.COMPLETE)
    mock_provider.get_goal.side_effect = [active, completed]
    mock_provider.update_metadata.return_value = completed

    await finalize_goal_complete(
        mock_provider,
        active,
        source="agent_tool",
        defer_terminal_callback=True,
    )

    mock_provider.update_status.assert_called_once_with("g-1", GoalStatus.COMPLETE)
    mock_provider.update_metadata.assert_called_once_with(
        "g-1",
        {"completion_source": "agent_tool", PENDING_TERMINAL_KEY: True},
    )


@pytest.mark.asyncio
async def test_resolve_deferred_tool_completion(mock_provider):
    completed = _goal(GoalStatus.COMPLETE)
    completed.metadata[PENDING_TERMINAL_KEY] = True
    mock_provider.get_latest_goal.return_value = completed
    mock_provider.update_metadata.return_value = completed

    decision = await resolve_deferred_tool_completion(mock_provider, "sess-1")

    assert decision is not None
    assert decision.verdict == "done"
    assert decision.should_continue is False
    mock_provider.update_metadata.assert_called_once_with("g-1", {PENDING_TERMINAL_KEY: False})


@pytest.mark.asyncio
async def test_resolve_deferred_tool_completion_none_without_flag(mock_provider):
    completed = _goal(GoalStatus.COMPLETE)
    mock_provider.get_latest_goal.return_value = completed

    decision = await resolve_deferred_tool_completion(mock_provider, "sess-1")
    assert decision is None
