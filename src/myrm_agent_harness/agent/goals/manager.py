"""GoalManager state machine and lifecycle control.

[INPUT]
- .protocols::GoalProvider (POS: GoalProvider protocol)
- .types::Goal, GoalStatus, GoalBudget, GoalAccountingOutcome (POS: Goal data types)
- .storage::GoalStorage (POS: SQLite persistence)

[OUTPUT]
- GoalManager: Implementation of GoalProvider.

[POS]
Core state machine for the Goal engine. Handles creation, status transitions,
usage accounting, continuation suppression, progress tracking, and loop restart recording.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from myrm_agent_harness.observability.metrics.goal_metrics import (
    record_goal_created,
    record_goal_objective_updated,
    record_goal_resumed,
    record_goal_terminal,
)

from .manager_queue_mixin import GoalManagerQueueMixin
from .protocols import GoalProvider
from .storage import GoalStorage
from .types import Goal, GoalAccountingOutcome, GoalBudget, GoalStatus

if TYPE_CHECKING:
    from myrm_agent_harness.agent.goals.verification.types import VerificationResult
    from myrm_agent_harness.toolkits.storage.base import StorageProvider

logger = logging.getLogger(__name__)

_METRIC_TERMINAL_STATES = frozenset(
    {GoalStatus.COMPLETE, GoalStatus.BUDGET_LIMITED, GoalStatus.PAUSED, GoalStatus.CANCELLED}
)


class GoalManager(GoalManagerQueueMixin, GoalProvider):
    """Implementation of GoalProvider managing goal lifecycle and state."""

    def __init__(self, storage_provider: StorageProvider) -> None:
        self._storage = GoalStorage(storage_provider)
        self._suppressed_sessions: set[str] = set()
        self._lock = asyncio.Lock()

    def to_dict(self) -> dict[str, object]:
        """Convert to dictionary for serialization."""
        return {
            "type": "GoalManager",
            "suppressed_sessions": list(self._suppressed_sessions),
        }

    async def get_latest_goal(self, session_id: str) -> Goal | None:
        """Get the latest goal for a session, regardless of status."""
        latest_id = await self._storage.get_latest_goal_id(session_id)
        if not latest_id:
            return None
        return await self.get_goal(latest_id)

    async def get_active_goal(self, session_id: str) -> Goal | None:
        """Get the currently active goal for a session, if any."""
        active_id = await self._storage.get_active_goal_id(session_id)
        if not active_id:
            return None

        goal = await self._storage.get_goal(active_id)
        if goal and goal.status == GoalStatus.ACTIVE:
            return goal

        return None

    async def get_goal(self, goal_id: str) -> Goal | None:
        """Get a specific goal by ID."""
        return await self._storage.get_goal(goal_id)

    async def create_goal(
        self,
        session_id: str,
        objective: str,
        budget: GoalBudget | None = None,
        metadata: dict[str, object] | None = None,
        acceptance_criteria: list[dict[str, object]] | None = None,
        constraints: list[str] | None = None,
        protected_paths: list[str] | None = None,
        ui_summary: str = "",
    ) -> Goal:
        """Create a new goal. If an active goal exists, queues the new goal instead."""
        active = await self.get_active_goal(session_id)

        status = GoalStatus.ACTIVE
        auto_approve = False
        if active:
            status = GoalStatus.QUEUED
            auto_approve = True

        goal = Goal(
            goal_id=str(uuid.uuid4()),
            session_id=session_id,
            objective=objective,
            status=status,
            ui_summary=ui_summary[:120] if ui_summary else "",
            budget=budget,
            auto_approve=auto_approve,
            constraints=constraints or [],
            protected_paths=protected_paths or [],
            metadata=metadata or {},
            acceptance_criteria=acceptance_criteria or [],
        )

        await self._storage.save_goal(goal)
        record_goal_created()
        if status == GoalStatus.QUEUED:
            await self._storage.add_to_queue(goal)
            logger.info(
                "Queued goal %s for session %s (priority=%d)",
                goal.goal_id,
                session_id,
                goal.priority,
            )
        else:
            logger.info("Created new goal %s for session %s", goal.goal_id, session_id)
        return goal

    async def update_budget(self, goal_id: str, additional_tokens: int) -> Goal:
        """Add tokens to the budget of a goal.

        If the goal was BUDGET_LIMITED, this does NOT automatically resume it.
        The caller must explicitly call update_status to resume.
        """
        goal = await self.get_goal(goal_id)
        if not goal:
            raise ValueError(f"Goal {goal_id} not found")

        if not goal.budget:
            # If no budget existed, create one with the additional tokens
            goal.budget = GoalBudget(max_tokens=additional_tokens)
        else:
            # GoalBudget is frozen, need to replace it
            new_max = (
                additional_tokens if goal.budget.max_tokens is None else goal.budget.max_tokens + additional_tokens
            )
            goal.budget = GoalBudget(
                max_tokens=new_max,
                max_usd=goal.budget.max_usd,
                max_time_seconds=goal.budget.max_time_seconds,
                max_turns=goal.budget.max_turns,
                convergence_window=goal.budget.convergence_window,
                loop_on_pause=goal.budget.loop_on_pause,
                max_loop_restarts=goal.budget.max_loop_restarts,
            )

        goal.updated_at = datetime.now(UTC)
        await self._storage.save_goal(goal)
        logger.info("Added %d tokens to budget for goal %s", additional_tokens, goal_id)
        return goal

    async def set_budget(self, goal_id: str, budget: GoalBudget) -> Goal:
        """Set or replace the entire budget of a goal."""
        goal = await self.get_goal(goal_id)
        if not goal:
            raise ValueError(f"Goal {goal_id} not found")

        goal.budget = budget
        goal.updated_at = datetime.now(UTC)
        await self._storage.save_goal(goal)
        logger.info("Set new budget for goal %s", goal_id)
        return goal

    async def update_status(self, goal_id: str, status: GoalStatus) -> Goal:
        """Update goal status."""
        goal = await self._storage.get_goal(goal_id)
        if not goal:
            raise ValueError(f"Goal {goal_id} not found")

        old_status = goal.status
        if old_status == status:
            return goal

        # Terminal states cannot be changed
        if old_status in (GoalStatus.COMPLETE, GoalStatus.CANCELLED):
            raise ValueError(f"Cannot change status of terminal goal {goal_id} ({old_status.value})")

        goal.status = status
        goal.updated_at = datetime.now(UTC)
        await self._storage.save_goal(goal)

        if status in _METRIC_TERMINAL_STATES:
            duration_s = (goal.updated_at - goal.created_at).total_seconds()
            record_goal_terminal(status.value, duration_s, goal.tokens_used, goal.cost_usd)

        if status in (GoalStatus.CANCELLED, GoalStatus.COMPLETE):
            from .invariant_snapshot import clear_snapshot

            clear_snapshot(goal_id)

        logger.info("Goal %s status changed: %s -> %s", goal_id, old_status.value, status.value)
        return goal

    async def increment_verification_retries(self, goal_id: str) -> Goal:
        """Increment the verification retry counter for a goal."""
        goal = await self._storage.get_goal(goal_id)
        if not goal:
            raise ValueError(f"Goal {goal_id} not found")

        goal.verification_retries += 1
        goal.updated_at = datetime.now(UTC)
        await self._storage.save_goal(goal)

        logger.info(
            "Goal %s verification retries incremented to %d",
            goal_id,
            goal.verification_retries,
        )
        return goal

    async def reset_verification_retries(self, goal_id: str) -> Goal:
        """Reset the verification retry counter to 0."""
        goal = await self._storage.get_goal(goal_id)
        if not goal:
            raise ValueError(f"Goal {goal_id} not found")

        goal.verification_retries = 0
        goal.updated_at = datetime.now(UTC)
        await self._storage.save_goal(goal)

        logger.info("Goal %s verification retries reset to 0", goal_id)
        return goal

    async def record_progress(self, goal_id: str, *, made_progress: bool) -> Goal:
        """Update the no-progress streak counter for convergence detection."""
        goal = await self._storage.get_goal(goal_id)
        if not goal:
            raise ValueError(f"Goal {goal_id} not found")

        if made_progress:
            goal.no_progress_streak = 0
        else:
            goal.no_progress_streak += 1

        goal.updated_at = datetime.now(UTC)
        await self._storage.save_goal(goal)
        return goal

    async def record_judge_parse_result(self, goal_id: str, *, parse_failed: bool) -> Goal:
        """Update the consecutive judge parse failure counter."""
        goal = await self._storage.get_goal(goal_id)
        if not goal:
            raise ValueError(f"Goal {goal_id} not found")

        if parse_failed:
            goal.consecutive_judge_parse_failures += 1
        else:
            goal.consecutive_judge_parse_failures = 0

        goal.updated_at = datetime.now(UTC)
        await self._storage.save_goal(goal)
        return goal

    async def record_loop_restart(self, goal_id: str) -> Goal:
        """Increment the loop_restarts counter."""
        goal = await self._storage.get_goal(goal_id)
        if not goal:
            raise ValueError(f"Goal {goal_id} not found")

        goal.loop_restarts += 1
        goal.updated_at = datetime.now(UTC)
        await self._storage.save_goal(goal)
        logger.info("Goal %s loop restart #%d", goal_id, goal.loop_restarts)
        return goal

    async def resume_goal(self, goal_id: str, *, reset_turns: bool = True) -> Goal:
        """Resume a paused/budget-limited goal.

        Transitions status back to ACTIVE, resets convergence counters
        (no_progress_streak, loop_restarts, verification_retries),
        and optionally resets turns_used.
        """
        goal = await self._storage.get_goal(goal_id)
        if not goal:
            raise ValueError(f"Goal {goal_id} not found")

        if goal.is_terminal:
            raise ValueError(f"Cannot resume terminal goal {goal_id} ({goal.status.value})")

        goal.status = GoalStatus.ACTIVE
        if reset_turns:
            goal.turns_used = 0
        goal.no_progress_streak = 0
        goal.loop_restarts = 0
        goal.consecutive_judge_parse_failures = 0
        goal.verification_retries = 0
        goal.metadata.pop("pause_reason", None)
        goal.updated_at = datetime.now(UTC)
        await self._storage.save_goal(goal)
        record_goal_resumed()

        logger.info(
            "Goal %s resumed (reset_turns=%s, turns_used=%d)",
            goal_id,
            reset_turns,
            goal.turns_used,
        )
        return goal

    async def evaluate_semantic(self, criteria: str, content: str) -> VerificationResult:
        """Evaluate a semantic criterion using an LLM judge.

        This must be implemented by the Server layer to inject the correct LLM context.
        """
        raise NotImplementedError(
            "Semantic evaluation must be implemented by the Server layer to provide LLM credentials."
        )

    async def account_usage(
        self,
        goal_id: str,
        token_delta: int,
        cost_delta: float,
        time_delta_seconds: int,
        turn_delta: int = 0,
    ) -> GoalAccountingOutcome:
        """Record usage and check against budget limits."""
        goal = await self._storage.get_goal(goal_id)
        if not goal:
            raise ValueError(f"Goal {goal_id} not found")

        if goal.status != GoalStatus.ACTIVE:
            return GoalAccountingOutcome(goal=goal, status_changed=False, budget_exhausted=False)

        goal.tokens_used += max(0, token_delta)
        goal.cost_usd += max(0.0, cost_delta)
        goal.time_used_seconds += max(0, time_delta_seconds)
        goal.turns_used += max(0, turn_delta)
        goal.updated_at = datetime.now(UTC)

        budget_exhausted = False
        if goal.budget:
            logger.debug(
                "Goal %s usage: tokens=%d/%s, cost=%.4f/%s, turns=%d/%s",
                goal_id,
                goal.tokens_used,
                goal.budget.max_tokens,
                goal.cost_usd,
                goal.budget.max_usd,
                goal.turns_used,
                goal.budget.max_turns,
            )
            if (
                (goal.budget.max_tokens is not None and goal.tokens_used >= goal.budget.max_tokens)
                or (goal.budget.max_usd is not None and goal.cost_usd >= goal.budget.max_usd)
                or (goal.budget.max_time_seconds is not None and goal.time_used_seconds >= goal.budget.max_time_seconds)
                or (goal.budget.max_turns is not None and goal.turns_used >= goal.budget.max_turns)
            ):
                budget_exhausted = True

        status_changed = False
        if budget_exhausted:
            goal.status = GoalStatus.BUDGET_LIMITED
            status_changed = True
            logger.warning("Goal %s reached budget limit", goal_id)

        await self._storage.save_goal(goal)

        return GoalAccountingOutcome(goal=goal, status_changed=status_changed, budget_exhausted=budget_exhausted)

    async def is_continuation_suppressed(self, session_id: str) -> bool:
        """Check if automatic continuation is suppressed."""
        async with self._lock:
            return session_id in self._suppressed_sessions

    async def suppress_continuation(self, session_id: str) -> None:
        """Suppress automatic continuation for the current turn."""
        async with self._lock:
            self._suppressed_sessions.add(session_id)

    async def reset_suppression(self, session_id: str) -> None:
        """Reset the continuation suppression flag."""
        async with self._lock:
            self._suppressed_sessions.discard(session_id)
