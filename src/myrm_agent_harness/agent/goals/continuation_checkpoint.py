"""Per-todo checkpoint guard for Goal continuation.

[INPUT]
- .types::Goal, GoalStatus, ContinuationDecision (POS: Goal data types)
- .protocols::GoalProvider (POS: Goal provider protocol)
- agent.meta_tools.progress.storage::read_todos_sync_from_workspace (POS: Workspace todos reader)
- agent.middlewares._session_context::get_workspace_root (POS: Workspace root accessor)

[OUTPUT]
- check_todo_checkpoint: Returns ContinuationDecision if new todos completed, else None.

[POS]
Implements the per-todo checkpoint mechanism (step 6.5c in the guard chain).
When checkpoint_mode=="per_todo", detects newly completed todos by comparing
current workspace state against a metadata snapshot, then PAUSES the goal
for user confirmation.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .types import ContinuationDecision, GoalStatus

if TYPE_CHECKING:
    from .protocols import GoalProvider
    from .types import Goal

logger = logging.getLogger(__name__)

_CHECKPOINT_SNAPSHOT_KEY = "_checkpoint_completed_ids"


async def check_todo_checkpoint(
    goal_provider: GoalProvider,
    goal: Goal,
) -> ContinuationDecision | None:
    """Check if new todos were completed and PAUSE for user confirmation.

    Returns None if checkpoint_mode is disabled, no workspace, or no new completions.
    Returns a ContinuationDecision with checkpoint_pause verdict otherwise.
    """
    if goal.checkpoint_mode != "per_todo":
        return None

    from myrm_agent_harness.agent.meta_tools.progress.storage import (
        read_todos_sync_from_workspace,
    )
    from myrm_agent_harness.agent.middlewares._session_context import (
        get_workspace_root,
    )

    ws_root = get_workspace_root()
    if not ws_root:
        return None

    store = read_todos_sync_from_workspace(ws_root)
    if not store or not store.todos:
        return None

    current_completed = {t.id for t in store.todos if t.status.value == "completed"}
    if not current_completed:
        return None

    prev_snapshot: list[str] = goal.metadata.get(_CHECKPOINT_SNAPSHOT_KEY, [])  # type: ignore[assignment]
    prev_ids = set(prev_snapshot) if isinstance(prev_snapshot, list) else set()

    newly_completed = current_completed - prev_ids
    if not newly_completed:
        return None

    newly_completed_names = [
        t.content for t in store.todos if t.id in newly_completed
    ]
    total_todos = len(store.todos)
    total_completed = len(current_completed)

    await goal_provider.update_metadata(
        goal.goal_id,
        {
            _CHECKPOINT_SNAPSHOT_KEY: sorted(current_completed),
            "pause_reason": (
                f"Checkpoint: completed {', '.join(newly_completed_names[:3])}"
                f" ({total_completed}/{total_todos})"
            ),
        },
    )
    await goal_provider.update_status(goal.goal_id, GoalStatus.PAUSED)

    logger.info(
        "Goal %s checkpoint pause: %d new todo(s) completed (%d/%d total)",
        goal.goal_id,
        len(newly_completed),
        total_completed,
        total_todos,
    )

    return ContinuationDecision(
        should_continue=False,
        verdict="checkpoint_pause",
        reason=(
            f"Checkpoint: {len(newly_completed)} todo(s) completed "
            f"({total_completed}/{total_todos})"
        ),
        turns_used=goal.turns_used,
        max_turns=goal.budget.max_turns if goal.budget else None,
    )
