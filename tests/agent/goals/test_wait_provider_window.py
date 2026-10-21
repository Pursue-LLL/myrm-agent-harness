"""Goal parking for a provider rate-limit window, against a real GoalManager."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from myrm_agent_harness.agent.goals.continuation import check_continuation
from myrm_agent_harness.agent.goals.manager import GoalManager
from myrm_agent_harness.agent.goals.types import GoalBudget, GoalStatus
from myrm_agent_harness.agent.goals.wait_provider_window import (
    MAX_NO_PROGRESS_HOLDS,
    PAUSE_KIND_KEY,
    WAIT_KIND_KEY,
    WAIT_KIND_USAGE_LIMIT,
    WAIT_RESUME_AT_KEY,
    park_goal_for_provider_window,
    pause_goal_after_missed_wake,
)
from myrm_agent_harness.toolkits.llms.errors.provider_window import HOLD_MAX_S, ProviderWindowHint, WindowSource
from myrm_agent_harness.toolkits.storage.local import LocalStorageBackend

SESSION = "chat-1"


@pytest.fixture
async def manager(tmp_path) -> GoalManager:
    return GoalManager(LocalStorageBackend(base_path=str(tmp_path)))


def _hint(wait_s: float) -> ProviderWindowHint:
    now = datetime.now(UTC).timestamp()
    return ProviderWindowHint(
        reset_at=now + wait_s, wait_s=wait_s, source=WindowSource.ANTHROPIC_UNIFIED, quota_window=True
    )


async def test_active_goal_is_parked_until_the_reset(manager: GoalManager) -> None:
    goal = await manager.create_goal(SESSION, "ship it", budget=GoalBudget(max_tokens=1000))
    hint = _hint(3600)

    parked = await park_goal_for_provider_window(manager, SESSION, hint)

    assert parked is not None
    assert parked.goal_id == goal.goal_id
    assert parked.status is GoalStatus.WAIT
    assert parked.metadata[WAIT_KIND_KEY] == WAIT_KIND_USAGE_LIMIT
    assert datetime.fromisoformat(str(parked.metadata[WAIT_RESUME_AT_KEY])).timestamp() == pytest.approx(hint.reset_at)
    # The cap is an int (continuation ignores any other type) and extends past the reset by the host's lateness tolerance.
    wait_max_seconds = parked.metadata["wait_max_seconds"]
    assert isinstance(wait_max_seconds, int)
    assert wait_max_seconds == int(hint.wait_s + HOLD_MAX_S)


@pytest.mark.parametrize(
    ("age_s", "verdict", "status"),
    [
        (30 * 60, "wait", GoalStatus.WAIT),  # a turn ends before the reset
        (3600 + 2 * 60, "wait", GoalStatus.WAIT),  # two minutes after the reset: the host has not woken the goal yet
        (3600 + 2 * 3600, "wait", GoalStatus.WAIT),  # the host was frozen for hours: still its call to make
        (3600 + int(HOLD_MAX_S) + 3600, "suppressed", GoalStatus.PAUSED),  # no host came for more than a day
    ],
)
async def test_a_turn_ending_late_leaves_the_wake_to_the_host_within_its_tolerance(
    manager: GoalManager, age_s: int, verdict: str, status: GoalStatus
) -> None:
    await manager.create_goal(SESSION, "ship it")
    parked = await park_goal_for_provider_window(manager, SESSION, _hint(3600))
    assert parked is not None
    stored = await manager.get_goal(parked.goal_id)
    assert stored is not None
    stored.metadata["wait_started_at"] = (datetime.now(UTC) - timedelta(seconds=age_s)).isoformat()
    await manager._storage.save_goal(stored)

    decision = await check_continuation(
        goal_provider=manager,
        session_id=SESSION,
        cancel_token=None,
        steering_token=None,
        collected_messages=[],
        tools_called_this_turn=False,
        net_tokens_this_turn=0,
        cost_this_turn=0.0,
        time_this_turn_seconds=1,
    )

    latest = await manager.get_latest_goal(SESSION)
    assert latest is not None
    assert decision.verdict == verdict
    assert latest.status is status


async def test_no_active_goal_returns_none(manager: GoalManager) -> None:
    assert await park_goal_for_provider_window(manager, SESSION, _hint(3600)) is None


async def test_reset_beyond_the_hold_cap_pauses_instead(manager: GoalManager) -> None:
    await manager.create_goal(SESSION, "ship it")

    paused = await park_goal_for_provider_window(manager, SESSION, _hint(3 * 86400))

    assert paused is not None
    assert paused.status is GoalStatus.PAUSED
    assert paused.metadata[PAUSE_KIND_KEY] == WAIT_KIND_USAGE_LIMIT
    assert WAIT_RESUME_AT_KEY in paused.metadata


async def test_holds_without_progress_end_in_a_pause(manager: GoalManager) -> None:
    goal = await manager.create_goal(SESSION, "ship it")

    for _ in range(MAX_NO_PROGRESS_HOLDS):
        parked = await park_goal_for_provider_window(manager, SESSION, _hint(600))
        assert parked is not None
        assert parked.status is GoalStatus.WAIT
        await manager.exit_wait(goal.goal_id)

    paused = await park_goal_for_provider_window(manager, SESSION, _hint(600))

    assert paused is not None
    assert paused.status is GoalStatus.PAUSED


async def test_a_completed_turn_resets_the_hold_streak(manager: GoalManager) -> None:
    goal = await manager.create_goal(SESSION, "ship it")

    for _ in range(MAX_NO_PROGRESS_HOLDS):
        await park_goal_for_provider_window(manager, SESSION, _hint(600))
        await manager.exit_wait(goal.goal_id)
        stored = await manager.get_goal(goal.goal_id)
        assert stored is not None
        stored.turns_used += 1  # a turn completed between the two limits
        await manager._storage.save_goal(stored)

    parked = await park_goal_for_provider_window(manager, SESSION, _hint(600))

    assert parked is not None
    assert parked.status is GoalStatus.WAIT


async def test_goal_paused_meanwhile_cannot_be_parked(manager: GoalManager) -> None:
    goal = await manager.create_goal(SESSION, "ship it")
    await manager.update_status(goal.goal_id, GoalStatus.PAUSED)

    assert await park_goal_for_provider_window(manager, SESSION, _hint(600)) is None


async def test_exit_wait_clears_the_wait_markers_but_keeps_the_streak(manager: GoalManager) -> None:
    goal = await manager.create_goal(SESSION, "ship it")
    await park_goal_for_provider_window(manager, SESSION, _hint(600))

    resumed = await manager.exit_wait(goal.goal_id)

    assert WAIT_KIND_KEY not in resumed.metadata
    assert WAIT_RESUME_AT_KEY not in resumed.metadata
    assert resumed.metadata["window_hold_streak"] == 1


async def test_resume_goal_forgets_every_provider_window_marker(manager: GoalManager) -> None:
    goal = await manager.create_goal(SESSION, "ship it")
    await park_goal_for_provider_window(manager, SESSION, _hint(3 * 86400))

    resumed = await manager.resume_goal(goal.goal_id)

    assert resumed.status is GoalStatus.ACTIVE
    for key in (
        PAUSE_KIND_KEY,
        WAIT_RESUME_AT_KEY,
        WAIT_KIND_KEY,
        "window_hold_streak",
        "window_hold_turns",
        "pause_reason",
    ):
        assert key not in resumed.metadata


async def test_missed_wake_ends_the_wait_and_pauses_for_the_user(manager: GoalManager) -> None:
    await manager.create_goal(SESSION, "ship it")
    parked = await park_goal_for_provider_window(manager, SESSION, _hint(600))
    assert parked is not None
    resume_at = parked.metadata[WAIT_RESUME_AT_KEY]

    paused = await pause_goal_after_missed_wake(manager, parked)

    assert paused.status is GoalStatus.PAUSED
    assert paused.metadata[PAUSE_KIND_KEY] == WAIT_KIND_USAGE_LIMIT
    assert paused.metadata[WAIT_RESUME_AT_KEY] == resume_at
    for key in (WAIT_KIND_KEY, "wait_reason", "wait_started_at", "wait_max_seconds"):
        assert key not in paused.metadata
