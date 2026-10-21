from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.agent.goals.continuation_git_drift import (
    GitDriftStatus,
    check_git_drift_and_rebase,
    inspect_git_drift,
)
from myrm_agent_harness.agent.goals.types import Goal, GoalStatus


@pytest.fixture
def mock_goal():
    return Goal(
        goal_id="g-100",
        session_id="s-100",
        objective="Implement feature",
        status=GoalStatus.ACTIVE,
    )


@pytest.mark.asyncio
async def test_inspect_git_drift_non_git():
    with patch("myrm_agent_harness.agent.goals.continuation_git_drift._run_git_cmd") as mock_git:
        mock_git.return_value = (1, "fatal: not a git repository", "")
        status = await inspect_git_drift("/some/path")
        assert status.is_git_repo is False
        assert status.upstream is None
        assert status.behind_count == 0


@pytest.mark.asyncio
async def test_inspect_git_drift_with_upstream():
    with patch("myrm_agent_harness.agent.goals.continuation_git_drift._run_git_cmd") as mock_git:
        # 1: inside work tree -> (0, "true", "")
        # 2: upstream branch -> (0, "origin/main", "")
        # 3: behind count -> (0, "3", "")
        # 4: ahead count -> (0, "1", "")
        mock_git.side_effect = [
            (0, "true", ""),
            (0, "origin/main", ""),
            (0, "3", ""),
            (0, "1", ""),
        ]
        status = await inspect_git_drift("/workspace")
        assert status.is_git_repo is True
        assert status.upstream == "origin/main"
        assert status.behind_count == 3
        assert status.ahead_count == 1


@pytest.mark.asyncio
async def test_check_git_drift_rebase_success(mock_goal):
    provider = AsyncMock()
    with patch(
        "myrm_agent_harness.agent.middlewares._session_context.get_workspace_root",
        return_value="/workspace",
    ), patch(
        "myrm_agent_harness.agent.goals.continuation_git_drift.inspect_git_drift",
        return_value=GitDriftStatus(is_git_repo=True, upstream="origin/main", behind_count=2),
    ), patch(
        "myrm_agent_harness.agent.goals.continuation_git_drift._run_git_cmd",
        return_value=(0, "Successfully rebased", ""),
    ):
        decision = await check_git_drift_and_rebase(provider, mock_goal)
        assert decision is None
        provider.update_metadata.assert_called_once()
        meta = provider.update_metadata.call_args[0][1]
        assert meta["_last_git_drift_check"]["status"] == "success"
        assert meta["_last_git_drift_check"]["rebased_commits"] == 2


@pytest.mark.asyncio
async def test_check_git_drift_rebase_conflict_aborts_and_pauses(mock_goal):
    provider = AsyncMock()
    with patch(
        "myrm_agent_harness.agent.middlewares._session_context.get_workspace_root",
        return_value="/workspace",
    ), patch(
        "myrm_agent_harness.agent.goals.continuation_git_drift.inspect_git_drift",
        return_value=GitDriftStatus(is_git_repo=True, upstream="origin/main", behind_count=4),
    ), patch(
        "myrm_agent_harness.agent.goals.continuation_git_drift._run_git_cmd",
    ) as mock_git:
        # First call is git rebase --autostash origin/main -> fails with conflict
        # Second call is git rebase --abort -> succeeds
        mock_git.side_effect = [
            (1, "CONFLICT (content): Merge conflict in file.py", "error: could not apply"),
            (0, "", ""),
        ]
        decision = await check_git_drift_and_rebase(provider, mock_goal)
        assert decision is not None
        assert decision.should_continue is False
        assert decision.verdict == "drift_pause"
        assert "DRIFT_CONFLICT_HUMAN_ESCALATION" in decision.reason

        provider.update_status.assert_called_once_with(mock_goal.goal_id, GoalStatus.PAUSED)
        provider.update_metadata.assert_called_once()
        meta = provider.update_metadata.call_args[0][1]
        assert meta["_last_git_drift_check"]["status"] == "conflict_aborted"
