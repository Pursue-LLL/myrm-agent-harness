"""Goal interception — publish Goal-scoped invariants before the main agent loop.

[INPUT]
- .protocol::GoalProvider (POS: Goal provider protocol)

[OUTPUT]
- intercept_goal_and_plan: Applies protected paths and tamper snapshots for active goals.

[POS]
Pre-execution hook for Goal sessions. Multi-step progress is handled by the main
agent via ``todo_write`` during the run — no sub-agent plan generation here.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.language_models import BaseChatModel

from myrm_agent_harness.agent.goals.protocols import GoalProvider
from myrm_agent_harness.toolkits.storage.base import StorageProvider

logger = logging.getLogger(__name__)

MultimodalQuery = str | list[dict[str, Any]]


async def intercept_goal_and_plan(
    goal_provider: GoalProvider,
    session_id: str,
    query: MultimodalQuery,
    llm: BaseChatModel,
    storage_provider: StorageProvider,
) -> None:
    """Apply Goal-scoped session setup before the main agent loop starts."""
    _ = query, llm, storage_provider

    goal = await goal_provider.get_active_goal(session_id)
    if not goal:
        return

    from myrm_agent_harness.agent.middlewares._session_context import (
        get_workspace_root,
        set_protected_paths,
    )

    set_protected_paths(tuple(goal.protected_paths))

    if goal.protected_paths:
        from myrm_agent_harness.agent.goals.invariant_snapshot import (
            capture_protected_snapshot,
        )

        ws_root = get_workspace_root() or "."
        capture_protected_snapshot(goal.goal_id, goal.protected_paths, ws_root)

    logger.info("Goal %s session invariants applied (progress via todo_write).", goal.goal_id)


__all__ = ["intercept_goal_and_plan"]
