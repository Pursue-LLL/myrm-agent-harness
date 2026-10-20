"""Park a goal until a provider rate-limit window reopens.

[INPUT]
- agent.goals.protocols::GoalProvider (POS: goal lifecycle boundary contract)
- toolkits.llms.errors.provider_window::ProviderWindowHint, WindowKind, HOLD_MAX_S (POS: provider-stated retry boundary and the longest wait worth holding for)

[OUTPUT]
- WAIT_KIND_KEY / WAIT_RESUME_AT_KEY / WAIT_KIND_USAGE_LIMIT / PAUSE_KIND_KEY: goal metadata vocabulary
- PROVIDER_WINDOW_METADATA_KEYS: every metadata key this module writes (cleared on resume_goal)
- MAX_NO_PROGRESS_HOLDS: consecutive progress-free holds before the goal is paused instead
- park_goal_for_provider_window: ACTIVE goal -> WAIT until the reset, or PAUSED when waiting cannot help
- pause_goal_after_missed_wake: WAIT goal the host woke far too late -> PAUSED for the user to decide

[POS]
Goal-side half of provider-window recovery. The stream layer calls it when a usage
limit is hit; the host (server wake daemon) reads the same metadata to resume the
goal at ``wait_resume_at``. Only goal state changes here, no prompt is touched.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.llms.errors.provider_window import HOLD_MAX_S, ProviderWindowHint, WindowKind

from .types import Goal, GoalStatus

if TYPE_CHECKING:
    from .protocols import GoalProvider

WAIT_KIND_KEY = "wait_kind"
WAIT_RESUME_AT_KEY = "wait_resume_at"
WAIT_KIND_USAGE_LIMIT = "usage_limit"
PAUSE_KIND_KEY = "pause_kind"

MAX_NO_PROGRESS_HOLDS = 2

_HOLD_TURNS_KEY = "window_hold_turns"
_HOLD_STREAK_KEY = "window_hold_streak"

PROVIDER_WINDOW_METADATA_KEYS = (
    WAIT_KIND_KEY,
    WAIT_RESUME_AT_KEY,
    PAUSE_KIND_KEY,
    _HOLD_TURNS_KEY,
    _HOLD_STREAK_KEY,
)
_WAIT_REASON = "Provider usage limit reached; resuming automatically"
_PAUSE_REASON = "Provider usage limit reached; paused until it resets"


async def park_goal_for_provider_window(
    provider: GoalProvider,
    session_id: str,
    hint: ProviderWindowHint,
) -> Goal | None:
    """Move the session's ACTIVE goal to WAIT until ``hint.reset_at``.

    Returns the goal in its new state (WAIT, or PAUSED when the reset is beyond the
    hold cap or the goal already held without making progress), or None when the
    session has no ACTIVE goal.
    """
    goal = await provider.get_active_goal(session_id)
    if goal is None:
        return None

    resume_at = datetime.fromtimestamp(hint.reset_at, UTC)
    streak = _next_streak(goal)
    if hint.kind is WindowKind.BEYOND or streak > MAX_NO_PROGRESS_HOLDS:
        return await _pause(provider, goal.goal_id, resume_at.isoformat())

    await provider.update_metadata(goal.goal_id, {_HOLD_TURNS_KEY: goal.turns_used, _HOLD_STREAK_KEY: streak})
    # The wait expires only after the host's own lateness tolerance (HOLD_MAX_S past the reset), so a turn ending
    # after the reset cannot pause the goal before the host gets to wake it. Continuation ignores non-int caps.
    return await provider.enter_wait(
        goal.goal_id,
        reason=_WAIT_REASON,
        max_wait_seconds=int(hint.wait_s + HOLD_MAX_S),
        kind=WAIT_KIND_USAGE_LIMIT,
        resume_at=resume_at,
    )


async def pause_goal_after_missed_wake(provider: GoalProvider, goal: Goal) -> Goal:
    """End a usage-limit WAIT whose wake-up came too late and hand the decision to the user."""
    resume_at = goal.metadata.get(WAIT_RESUME_AT_KEY)
    await provider.exit_wait(goal.goal_id)
    return await _pause(provider, goal.goal_id, str(resume_at) if resume_at else "")


async def _pause(provider: GoalProvider, goal_id: str, resume_at: str) -> Goal:
    await provider.update_metadata(
        goal_id,
        {PAUSE_KIND_KEY: WAIT_KIND_USAGE_LIMIT, WAIT_RESUME_AT_KEY: resume_at, "pause_reason": _PAUSE_REASON},
    )
    return await provider.update_status(goal_id, GoalStatus.PAUSED)


def _next_streak(goal: Goal) -> int:
    """Holds in a row that ended without a single completed turn in between."""
    same_progress = goal.metadata.get(_HOLD_TURNS_KEY) == goal.turns_used
    previous = goal.metadata.get(_HOLD_STREAK_KEY)
    return previous + 1 if same_progress and isinstance(previous, int) else 1
