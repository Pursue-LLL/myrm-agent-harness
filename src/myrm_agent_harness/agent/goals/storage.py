"""SQLite-based goal persistence.

[INPUT]
- toolkits.storage.base::StorageProvider (POS: Storage protocol)
- .types::Goal, GoalStatus, GoalBudget (POS: Goal data types)

[OUTPUT]
- GoalStorage: SQLite implementation for goal persistence.

[POS]
Handles persistence of Goal state using the framework's standard StorageProvider.
Ensures goal state survives process restarts and thread recovery.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from .types import Goal, GoalBudget, GoalStatus

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.storage.base import StorageProvider

logger = logging.getLogger(__name__)

_GOAL_NAMESPACE = "goals"


class GoalStorage:
    """SQLite-based goal persistence using StorageProvider."""

    def __init__(self, storage: StorageProvider) -> None:
        self._storage = storage

    async def save_goal(self, goal: Goal) -> None:
        """Save goal state to storage."""
        data = self._serialize_goal(goal)
        await self._storage.write(
            key=f"{_GOAL_NAMESPACE}/{goal.goal_id}",
            content=json.dumps(data).encode("utf-8"),
        )

        # Maintain session -> active goal index
        if goal.status == GoalStatus.ACTIVE:
            await self._storage.write(
                key=f"{_GOAL_NAMESPACE}_active/{goal.session_id}",
                content=goal.goal_id.encode("utf-8"),
            )
        else:
            # If not active, check if it was the active one and remove index
            active_id = await self.get_active_goal_id(goal.session_id)
            if active_id == goal.goal_id:
                await self._storage.delete(key=f"{_GOAL_NAMESPACE}_active/{goal.session_id}")

        # Always maintain latest goal index
        await self._storage.write(
            key=f"{_GOAL_NAMESPACE}_latest/{goal.session_id}",
            content=goal.goal_id.encode("utf-8"),
        )

    async def get_goal(self, goal_id: str) -> Goal | None:
        """Retrieve goal by ID."""
        try:
            raw = await self._storage.read(key=f"{_GOAL_NAMESPACE}/{goal_id}")
            if not raw:
                return None

            data = json.loads(raw.decode("utf-8"))
            return self._deserialize_goal(data)
        except Exception as e:
            logger.error("Failed to deserialize goal %s: %s", goal_id, e)
            return None

    async def get_active_goal_id(self, session_id: str) -> str | None:
        """Get the ID of the currently active goal for a session."""
        try:
            raw = await self._storage.read(key=f"{_GOAL_NAMESPACE}_active/{session_id}")
            if not raw:
                return None
            return raw.decode("utf-8")
        except Exception:
            return None

    async def list_active_sessions(self) -> list[str]:
        """Return all session_ids that currently have an ACTIVE goal."""
        prefix = f"{_GOAL_NAMESPACE}_active/"
        try:
            keys = await self._storage.list(prefix=prefix)
            return [k.removeprefix(prefix) for k in keys if k.startswith(prefix)]
        except Exception:
            logger.warning("Failed to enumerate active goal sessions", exc_info=True)
            return []

    async def get_latest_goal_id(self, session_id: str) -> str | None:
        """Get the ID of the latest goal for a session."""
        try:
            raw = await self._storage.read(key=f"{_GOAL_NAMESPACE}_latest/{session_id}")
            if not raw:
                return None
            return raw.decode("utf-8")
        except Exception:
            return None

    def _serialize_goal(self, goal: Goal) -> dict[str, object]:
        budget_dict = None
        if goal.budget:
            budget_dict = {
                "max_tokens": goal.budget.max_tokens,
                "max_usd": goal.budget.max_usd,
                "max_time_seconds": goal.budget.max_time_seconds,
                "max_turns": goal.budget.max_turns,
                "convergence_window": goal.budget.convergence_window,
                "loop_on_pause": goal.budget.loop_on_pause,
                "max_loop_restarts": goal.budget.max_loop_restarts,
            }

        return {
            "goal_id": goal.goal_id,
            "session_id": goal.session_id,
            "objective": goal.objective,
            "status": goal.status.value,
            "ui_summary": goal.ui_summary,
            "priority": goal.priority,
            "auto_approve": goal.auto_approve,
            "constraints": goal.constraints,
            "protected_paths": goal.protected_paths,
            "budget": budget_dict,
            "acceptance_criteria": goal.acceptance_criteria,
            "subgoals": goal.subgoals,
            "verification_retries": goal.verification_retries,
            "tokens_used": goal.tokens_used,
            "time_used_seconds": goal.time_used_seconds,
            "cost_usd": goal.cost_usd,
            "turns_used": goal.turns_used,
            "no_progress_streak": goal.no_progress_streak,
            "loop_restarts": goal.loop_restarts,
            "consecutive_judge_parse_failures": goal.consecutive_judge_parse_failures,
            "created_at": goal.created_at.isoformat(),
            "updated_at": goal.updated_at.isoformat(),
            "metadata": goal.metadata,
        }

    def _deserialize_goal(self, data: dict[str, object]) -> Goal:
        budget = None
        if data.get("budget"):
            b_data = data["budget"]
            budget = GoalBudget(
                max_tokens=b_data.get("max_tokens"),
                max_usd=b_data.get("max_usd"),
                max_time_seconds=b_data.get("max_time_seconds"),
                max_turns=b_data.get("max_turns"),
                convergence_window=b_data.get("convergence_window"),
                loop_on_pause=b_data.get("loop_on_pause", False),
                max_loop_restarts=b_data.get("max_loop_restarts", 10),
            )

        return Goal(
            goal_id=data["goal_id"],
            session_id=data["session_id"],
            objective=data["objective"],
            status=GoalStatus(data["status"]),
            ui_summary=data.get("ui_summary", ""),
            priority=data.get("priority", 0),
            auto_approve=data.get("auto_approve", False),
            constraints=data.get("constraints", []),
            protected_paths=data.get("protected_paths", []),
            budget=budget,
            acceptance_criteria=data.get("acceptance_criteria", []),
            subgoals=data.get("subgoals", []),
            verification_retries=data.get("verification_retries", 0),
            tokens_used=data.get("tokens_used", 0),
            time_used_seconds=data.get("time_used_seconds", 0),
            cost_usd=data.get("cost_usd", 0.0),
            turns_used=data.get("turns_used", 0),
            no_progress_streak=data.get("no_progress_streak", 0),
            loop_restarts=data.get("loop_restarts", 0),
            consecutive_judge_parse_failures=data.get("consecutive_judge_parse_failures", 0),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            metadata=data.get("metadata", {}),
        )

    async def save_stash(
        self,
        branch_name: str,
        session_id: str,
        goal_id: str,
        progress_state: dict[str, Any] | None,
        chat_history: list[dict[str, Any]] | None,
    ) -> None:
        """Save a stashed goal state for a branch."""

        data = {
            "session_id": session_id,
            "goal_id": goal_id,
            "progress_state": progress_state,
            "chat_history": chat_history,
            "stashed_at": datetime.now().isoformat(),
        }
        await self._storage.write(
            key=f"{_GOAL_NAMESPACE}_stash/{session_id}/{branch_name}",
            content=json.dumps(data).encode("utf-8"),
        )

    async def get_stash(self, session_id: str, branch_name: str) -> dict[str, Any] | None:
        """Retrieve a stashed goal state for a branch."""

        try:
            raw = await self._storage.read(key=f"{_GOAL_NAMESPACE}_stash/{session_id}/{branch_name}")
            if not raw:
                return None
            return json.loads(raw.decode("utf-8"))
        except Exception as e:
            logger.debug("Failed to read stash for branch %s: %s", branch_name, e)
            return None

    async def delete_stash(self, session_id: str, branch_name: str) -> None:
        """Delete stashed goal state for a branch."""
        try:
            await self._storage.delete(key=f"{_GOAL_NAMESPACE}_stash/{session_id}/{branch_name}")
        except Exception as e:
            logger.error("Failed to delete stash for branch %s: %s", branch_name, e)

    # --- Queue index operations ---

    async def add_to_queue(self, goal: Goal) -> None:
        """Add a goal to the session queue index."""
        queue = await self._get_raw_queue(goal.session_id)
        entry = {
            "goal_id": goal.goal_id,
            "priority": goal.priority,
            "created_at": goal.created_at.isoformat(),
        }
        queue.append(entry)
        queue.sort(key=lambda e: (e["priority"], e["created_at"]))
        await self._save_raw_queue(goal.session_id, queue)

    async def get_queue(self, session_id: str) -> list[dict[str, object]]:
        """Get the ordered queue entries for a session."""
        return await self._get_raw_queue(session_id)

    async def remove_from_queue(self, session_id: str, goal_id: str) -> None:
        """Remove a goal from the queue index."""
        queue = await self._get_raw_queue(session_id)
        queue = [e for e in queue if e["goal_id"] != goal_id]
        await self._save_raw_queue(session_id, queue)

    async def reorder_queue(self, session_id: str, ordered_goal_ids: list[str]) -> None:
        """Reorder queue by assigning priorities based on the provided order."""
        queue = await self._get_raw_queue(session_id)
        id_to_entry = {e["goal_id"]: e for e in queue}
        reordered: list[dict[str, object]] = []
        for i, gid in enumerate(ordered_goal_ids):
            if gid in id_to_entry:
                entry = id_to_entry.pop(gid)
                entry["priority"] = i
                reordered.append(entry)
        for entry in id_to_entry.values():
            entry["priority"] = len(reordered)
            reordered.append(entry)
        await self._save_raw_queue(session_id, reordered)

    async def _get_raw_queue(self, session_id: str) -> list[dict[str, object]]:
        try:
            raw = await self._storage.read(key=f"{_GOAL_NAMESPACE}_queue/{session_id}")
            if not raw:
                return []
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return []

    async def _save_raw_queue(self, session_id: str, queue: list[dict[str, object]]) -> None:
        await self._storage.write(
            key=f"{_GOAL_NAMESPACE}_queue/{session_id}",
            content=json.dumps(queue).encode("utf-8"),
        )
