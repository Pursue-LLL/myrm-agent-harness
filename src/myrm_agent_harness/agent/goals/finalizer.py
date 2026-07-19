"""GoalFinalizer — single SSOT path for marking goals COMPLETE.

[INPUT]
- .protocols::GoalProvider (POS: Goal lifecycle contract)
- .types::Goal, GoalStatus, ContinuationDecision (POS: Goal data types)

[OUTPUT]
- finalize_goal_complete: Idempotent COMPLETE transition with optional deferred terminal callback
- resolve_deferred_tool_completion: Continuation hook for agent-tool completion path

[POS]
Ensures all COMPLETE transitions share one code path and that tool-initiated completions
still trigger the terminal pipeline (learnings, queue dequeue, GOAL_TERMINAL).
"""

from __future__ import annotations

import logging
from typing import Literal

from .protocols import GoalProvider
from .types import ContinuationDecision, ContinuationVerdict, Goal, GoalStatus

logger = logging.getLogger(__name__)

PENDING_TERMINAL_KEY = "pending_terminal"
COMPLETION_SOURCE_KEY = "completion_source"

CompletionSource = Literal["semantic_judge", "convergence", "agent_tool"]


def _make_decision(
    verdict: ContinuationVerdict,
    reason: str,
    goal: Goal,
    *,
    should_continue: bool = False,
    message: str = "",
) -> ContinuationDecision:
    max_turns = goal.budget.max_turns if goal.budget else None
    return ContinuationDecision(
        should_continue=should_continue,
        verdict=verdict,
        reason=reason,
        turns_used=goal.turns_used,
        max_turns=max_turns,
        message=message,
    )


async def finalize_goal_complete(
    goal_provider: GoalProvider,
    goal: Goal,
    *,
    source: CompletionSource,
    defer_terminal_callback: bool = False,
) -> Goal:
    """Mark a goal COMPLETE through the single SSOT path.

    Idempotent: if the goal is already COMPLETE, returns the current record unchanged.
    When ``defer_terminal_callback`` is True (agent tool path), sets ``pending_terminal``
    so ``check_continuation`` emits a ``done`` verdict for ``on_goal_terminal``.
    """
    refreshed = await goal_provider.get_goal(goal.goal_id)
    if not refreshed:
        raise ValueError(f"Goal {goal.goal_id} not found")

    if refreshed.status == GoalStatus.COMPLETE:
        return refreshed

    if refreshed.is_terminal:
        raise ValueError(
            f"Cannot complete terminal goal {goal.goal_id} ({refreshed.status.value})"
        )

    await goal_provider.update_status(goal.goal_id, GoalStatus.COMPLETE)

    metadata_updates: dict[str, object] = {COMPLETION_SOURCE_KEY: source}
    if defer_terminal_callback:
        metadata_updates[PENDING_TERMINAL_KEY] = True

    updated = await goal_provider.update_metadata(goal.goal_id, metadata_updates)
    logger.info(
        "Goal %s finalized via %s (defer_terminal=%s)",
        goal.goal_id,
        source,
        defer_terminal_callback,
    )
    return updated


async def resolve_deferred_tool_completion(
    goal_provider: GoalProvider,
    session_id: str,
) -> ContinuationDecision | None:
    """Resolve a tool-initiated COMPLETE that deferred the terminal callback."""
    latest = await goal_provider.get_latest_goal(session_id)
    if not latest or latest.status != GoalStatus.COMPLETE:
        return None
    if not latest.metadata.get(PENDING_TERMINAL_KEY):
        return None

    await goal_provider.update_metadata(latest.goal_id, {PENDING_TERMINAL_KEY: False})

    logger.info("Goal %s: resolving deferred tool completion → terminal pipeline", latest.goal_id)
    return _make_decision(
        "done",
        "Goal completed via complete_goal_tool",
        latest,
    )


__all__ = [
    "COMPLETION_SOURCE_KEY",
    "PENDING_TERMINAL_KEY",
    "CompletionSource",
    "finalize_goal_complete",
    "resolve_deferred_tool_completion",
]
