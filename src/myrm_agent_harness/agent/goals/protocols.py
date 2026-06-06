"""GoalProvider protocol definition.

[INPUT]
- .types::Goal, GoalStatus, GoalBudget, GoalAccountingOutcome (POS: Goal data types)

[OUTPUT]
- GoalProvider: Protocol for goal lifecycle management and accounting.

[POS]
Defines the boundary contract for the Goal engine. StreamExecutor and other
framework components interact with goals exclusively through this protocol.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from .types import Goal, GoalAccountingOutcome, GoalBudget, GoalStatus

if TYPE_CHECKING:
    from .verification.base import VerificationResult


@runtime_checkable
class GoalProvider(Protocol):
    """Protocol for goal lifecycle management and accounting.

    Implementations (like GoalManager) handle the persistence and state machine
    logic, while StreamExecutor uses this protocol to drive the autonomous loop.
    """

    async def get_latest_goal(self, session_id: str) -> Goal | None:
        """Get the latest goal for a session, regardless of status."""
        ...

    async def get_active_goal(self, session_id: str) -> Goal | None:
        """Get the currently active goal for a session, if any."""
        ...

    async def get_goal(self, goal_id: str) -> Goal | None:
        """Get a specific goal by ID."""
        ...

    async def create_goal(
        self,
        session_id: str,
        objective: str,
        budget: GoalBudget | None = None,
        metadata: dict[str, object] | None = None,
        acceptance_criteria: list[dict[str, object]] | None = None,
        constraints: list[str] | None = None,
        ui_summary: str = "",
    ) -> Goal:
        """Create a new goal. If an active goal exists, queues the new goal instead."""
        ...

    async def update_budget(self, goal_id: str, additional_tokens: int) -> Goal:
        """Add tokens to the budget of a goal."""
        ...

    async def set_budget(self, goal_id: str, budget: GoalBudget) -> Goal:
        """Set or replace the entire budget of a goal."""
        ...

    async def update_status(self, goal_id: str, status: GoalStatus) -> Goal:
        """Update goal status (e.g., pause, resume, complete)."""
        ...

    async def increment_verification_retries(self, goal_id: str) -> Goal:
        """Increment the verification retry counter for a goal."""
        ...

    async def reset_verification_retries(self, goal_id: str) -> Goal:
        """Reset the verification retry counter to 0."""
        ...

    async def account_usage(
        self,
        goal_id: str,
        token_delta: int,
        cost_delta: float,
        time_delta_seconds: int,
        turn_delta: int = 0,
    ) -> GoalAccountingOutcome:
        """Record usage and check against budget limits.

        If any budget dimension is exhausted, automatically transitions to BUDGET_LIMITED.
        """
        ...

    async def is_continuation_suppressed(self, session_id: str) -> bool:
        """Check if automatic continuation is suppressed (e.g., due to zero tool calls)."""
        ...

    async def suppress_continuation(self, session_id: str) -> None:
        """Suppress automatic continuation for the current turn."""
        ...

    async def reset_suppression(self, session_id: str) -> None:
        """Reset the continuation suppression flag."""
        ...

    async def add_subgoal(self, goal_id: str, text: str) -> dict[str, object]:
        """Add a new subgoal to an existing goal."""
        ...

    async def remove_subgoal(self, goal_id: str, index: int) -> dict[str, object]:
        """Remove a subgoal by index (0-based)."""
        ...

    async def clear_subgoals(self, goal_id: str) -> int:
        """Clear all subgoals for a goal. Returns the number of subgoals removed."""
        ...

    async def resume_goal(self, goal_id: str, *, reset_turns: bool = True) -> Goal:
        """Resume a paused/budget-limited goal.

        Transitions status back to ACTIVE, resets convergence counters
        (no_progress_streak, loop_restarts), and optionally resets turns_used.
        """
        ...

    async def evaluate_semantic(
        self, criteria: str, content: str, context_messages: list[Any] | None = None
    ) -> VerificationResult:
        """Evaluate a semantic criterion using an LLM judge."""
        ...

    async def stash_goal(
        self,
        session_id: str,
        branch_name: str,
        planner_state: dict[str, Any] | None = None,
        chat_history: list[dict[str, Any]] | None = None,
    ) -> bool:
        """Stash active goal state, planner progress, and short-term chat memory."""
        ...

    async def restore_goal(
        self,
        session_id: str,
        branch_name: str,
    ) -> dict[str, Any] | None:
        """Restore stashed goal state, returning the planner progress, goal, and chat history."""
        ...

    async def dequeue_next(self, session_id: str) -> Goal | None:
        """Dequeue the next QUEUED goal by priority ASC, created_at ASC.

        Transitions the goal from QUEUED → ACTIVE and sets auto_approve=True.
        Returns None if no queued goals exist.
        """
        ...

    async def get_queued_goals(self, session_id: str) -> list[Goal]:
        """Get all QUEUED goals for a session, ordered by priority ASC, created_at ASC."""
        ...

    async def cancel_queued_goal(self, session_id: str, goal_id: str) -> Goal:
        """Cancel a queued goal and remove it from the queue index."""
        ...

    async def reorder_queue(self, session_id: str, ordered_goal_ids: list[str]) -> None:
        """Reorder the goal queue by the provided ordered goal IDs."""
        ...

    async def record_progress(self, goal_id: str, *, made_progress: bool) -> Goal:
        """Update the no-progress streak counter for convergence detection.

        If made_progress=True, resets streak to 0. Otherwise increments by 1.
        """
        ...

    async def record_loop_restart(self, goal_id: str) -> Goal:
        """Increment the loop_restarts counter."""
        ...

    async def update_constraints(self, goal_id: str, constraints: list[str]) -> Goal:
        """Set or replace the constraints list for a goal."""
        ...

    async def update_objective(self, goal_id: str, new_objective: str) -> Goal:
        """Update the objective text of a goal (runtime hot-edit)."""
        ...
