"""GoalManager subgoal and queue operations mixin.

[POS]
Queue/subgoal/stash operations mixin for GoalManager.
"""

from __future__ import annotations

from datetime import UTC, datetime

from myrm_agent_harness.agent.goals.types import Goal, GoalStatus
from myrm_agent_harness.observability.metrics.goal_metrics import record_goal_objective_updated
from myrm_agent_harness.utils.logger_utils import get_agent_logger

logger = get_agent_logger(__name__)


class GoalManagerQueueMixin:
    async def add_subgoal(self, goal_id: str, text: str) -> dict[str, object]:
        """Add a new subgoal to an existing goal.

        Args:
            goal_id: The ID of the goal.
            text: The subgoal description.

        Returns:
            The added subgoal dictionary containing text and created_at.
        """
        goal = await self._storage.get_goal(goal_id)
        if not goal:
            raise ValueError(f"Goal {goal_id} not found")

        subgoal = {"text": text, "created_at": datetime.now(UTC).isoformat()}

        if goal.subgoals is None:
            goal.subgoals = []

        goal.subgoals.append(subgoal)
        goal.updated_at = datetime.now(UTC)
        await self._storage.save_goal(goal)

        logger.info("Added subgoal to goal %s: %s", goal_id, text)
        return subgoal

    async def remove_subgoal(self, goal_id: str, index: int) -> dict[str, object]:
        """Remove a subgoal by index (0-based)."""
        goal = await self._storage.get_goal(goal_id)
        if not goal:
            raise ValueError(f"Goal {goal_id} not found")

        if not goal.subgoals or index < 0 or index >= len(goal.subgoals):
            raise IndexError(f"Subgoal index {index} out of range")

        removed = goal.subgoals.pop(index)
        goal.updated_at = datetime.now(UTC)
        await self._storage.save_goal(goal)

        logger.info("Removed subgoal %d from goal %s: %s", index, goal_id, removed.get("text"))
        return removed

    async def clear_subgoals(self, goal_id: str) -> int:
        """Clear all subgoals for a goal. Returns the number of subgoals removed."""
        goal = await self._storage.get_goal(goal_id)
        if not goal:
            raise ValueError(f"Goal {goal_id} not found")

        count = len(goal.subgoals) if goal.subgoals else 0
        if count > 0:
            goal.subgoals.clear()
            goal.updated_at = datetime.now(UTC)
            await self._storage.save_goal(goal)
            logger.info("Cleared %d subgoals from goal %s", count, goal_id)

        return count

    async def dequeue_next(self, session_id: str) -> Goal | None:
        """Dequeue the next QUEUED goal by priority ASC, created_at ASC.

        Transitions the goal from QUEUED → ACTIVE and sets auto_approve=True.
        Returns None if no queued goals exist.
        """
        while True:
            queue_entries = await self._storage.get_queue(session_id)
            if not queue_entries:
                return None

            goal_id = queue_entries[0]["goal_id"]
            goal = await self.get_goal(goal_id)
            if not goal or goal.status != GoalStatus.QUEUED:
                await self._storage.remove_from_queue(session_id, goal_id)
                continue

            goal.status = GoalStatus.ACTIVE
            goal.auto_approve = True
            goal.updated_at = datetime.now(UTC)
            await self._storage.save_goal(goal)
            await self._storage.remove_from_queue(session_id, goal_id)

            logger.info("Dequeued goal %s for session %s", goal.goal_id, session_id)
            return goal

    async def get_queued_goals(self, session_id: str) -> list[Goal]:
        """Get all QUEUED goals for a session, ordered by priority ASC, created_at ASC."""
        queue_entries = await self._storage.get_queue(session_id)
        goals: list[Goal] = []
        for entry in queue_entries:
            goal = await self.get_goal(entry["goal_id"])
            if goal and goal.status == GoalStatus.QUEUED:
                goals.append(goal)
        return goals

    async def cancel_queued_goal(self, session_id: str, goal_id: str) -> Goal:
        """Cancel a queued goal and remove it from the queue index."""
        goal = await self.get_goal(goal_id)
        if not goal or goal.status != GoalStatus.QUEUED:
            raise ValueError(f"Goal {goal_id} is not in QUEUED status")
        updated = await self.update_status(goal_id, GoalStatus.CANCELLED)
        await self._storage.remove_from_queue(session_id, goal_id)
        return updated

    async def update_constraints(self, goal_id: str, constraints: list[str]) -> Goal:
        """Set or replace the constraints list for a goal."""
        goal = await self._storage.get_goal(goal_id)
        if not goal:
            raise ValueError(f"Goal {goal_id} not found")

        goal.constraints = constraints
        goal.updated_at = datetime.now(UTC)
        await self._storage.save_goal(goal)
        logger.info("Updated constraints for goal %s (%d items)", goal_id, len(constraints))
        return goal

    async def update_protected_paths(self, goal_id: str, protected_paths: list[str]) -> Goal:
        """Set or replace the protected_paths (glob patterns) for a goal."""
        goal = await self._storage.get_goal(goal_id)
        if not goal:
            raise ValueError(f"Goal {goal_id} not found")

        goal.protected_paths = protected_paths
        goal.updated_at = datetime.now(UTC)
        await self._storage.save_goal(goal)
        logger.info("Updated protected_paths for goal %s (%d patterns)", goal_id, len(protected_paths))
        return goal

    async def update_objective(self, goal_id: str, new_objective: str) -> Goal:
        """Update the objective text of a goal (runtime hot-edit)."""
        goal = await self._storage.get_goal(goal_id)
        if not goal:
            raise ValueError(f"Goal {goal_id} not found")
        if goal.is_terminal:
            raise ValueError(f"Cannot update objective of terminal goal {goal_id} (status={goal.status})")

        goal.objective = new_objective
        goal.updated_at = datetime.now(UTC)
        await self._storage.save_goal(goal)
        record_goal_objective_updated()
        logger.info("Updated objective for goal %s", goal_id)
        return goal

    async def record_acceptance_results(
        self, goal_id: str, results: list[dict[str, object]]
    ) -> Goal:
        """Persist per-criterion acceptance verification results."""
        goal = await self._storage.get_goal(goal_id)
        if not goal:
            raise ValueError(f"Goal {goal_id} not found")

        goal.metadata["acceptance_results"] = results

        history: list[dict[str, object]] = goal.metadata.get("acceptance_history", [])  # type: ignore[assignment]
        history.append({
            "timestamp": datetime.now(UTC).isoformat(),
            "results": results,
        })
        goal.metadata["acceptance_history"] = history

        goal.updated_at = datetime.now(UTC)
        await self._storage.save_goal(goal)
        logger.info(
            "Recorded acceptance results for goal %s (%d criteria, %d passed)",
            goal_id,
            len(results),
            sum(1 for r in results if r.get("passed")),
        )
        return goal

    async def reorder_queue(self, session_id: str, ordered_goal_ids: list[str]) -> None:
        """Reorder the goal queue by the provided ordered goal IDs."""
        await self._storage.reorder_queue(session_id, ordered_goal_ids)

    async def stash_goal(
        self,
        session_id: str,
        branch_name: str,
        progress_state: dict[str, Any] | None = None,
        chat_history: list[dict[str, Any]] | None = None,
    ) -> bool:
        """Stash active goal state, progress todos, and short-term chat memory."""

        goal = await self.get_active_goal(session_id)
        if not goal:
            logger.info(
                "No active goal to stash for session %s on branch %s",
                session_id,
                branch_name,
            )
            return False

        # Set goal status to PAUSED when stashed
        await self.update_status(goal.goal_id, GoalStatus.PAUSED)

        await self._storage.save_stash(
            branch_name=branch_name,
            session_id=session_id,
            goal_id=goal.goal_id,
            progress_state=progress_state,
            chat_history=chat_history,
        )
        logger.info(
            "Stashed goal %s for session %s on branch %s",
            goal.goal_id,
            session_id,
            branch_name,
        )
        return True

    async def restore_goal(
        self,
        session_id: str,
        branch_name: str,
    ) -> dict[str, Any] | None:
        """Restore stashed goal state, returning progress todos, goal, and chat history."""

        stash = await self._storage.get_stash(session_id, branch_name)
        if not stash:
            logger.info("No stash found for branch %s", branch_name)
            return None

        goal_id = stash["goal_id"]
        goal = await self.get_goal(goal_id)
        if not goal:
            logger.warning("Stashed goal %s not found in storage", goal_id)
            return None

        # Transition goal status back to ACTIVE when restored
        goal = await self.update_status(goal_id, GoalStatus.ACTIVE)

        # Delete stash after successful restore
        await self._storage.delete_stash(session_id, branch_name)

        logger.info("Restored stashed goal %s for branch %s", goal_id, branch_name)
        return {
            "goal": goal,
            "progress_state": stash.get("progress_state") or stash.get("planner_state"),
            "chat_history": stash.get("chat_history"),
        }
