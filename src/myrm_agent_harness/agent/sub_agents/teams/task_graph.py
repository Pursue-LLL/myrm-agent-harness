"""CAS Versioned Task Graph DAG engine for durable Agent Teams.

[INPUT]
- .types::(TeamTaskStatus, TeamTaskSnapshot, TeamTaskView,
           CASConflictError, TaskDependencyCycleError, TaskBlockedError)

[OUTPUT]
- TaskGraphEngine: task CRUD, CAS optimistic lock, DAG cycle check, readiness, write scope warnings

[POS]
Maintains the shared team task board with monotonic revision increments,
directed acyclic graph dependency resolution, and concurrent claim safety.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from .types import (
    CASConflictError,
    TaskBlockedError,
    TaskDependencyCycleError,
    TeamTaskSnapshot,
    TeamTaskStatus,
    TeamTaskView,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)


class TaskGraphEngine:
    """In-memory CAS task graph engine with DAG validation."""

    def __init__(self, team_id: str) -> None:
        self.team_id = team_id
        self._tasks: dict[str, TeamTaskSnapshot] = {}
        self._counter: int = 0

    def create_task(
        self,
        subject: str,
        description: str = "",
        blocked_by: Sequence[str] = (),
        write_scopes: Sequence[str] = (),
        owner_id: str | None = None,
        owner_name: str | None = None,
    ) -> TeamTaskView:
        """Create a new task at revision 1 and validate DAG."""
        proposed_id = f"task-{self._counter + 1}"

        # Clean and validate blocked_by dependencies
        clean_blocked_by = tuple(b.strip() for b in blocked_by if b.strip())
        self._validate_dependencies(proposed_id, clean_blocked_by)

        self._counter += 1
        task_id = proposed_id

        now = time.time()
        initial_status = TeamTaskStatus.IN_PROGRESS if owner_id else TeamTaskStatus.PENDING

        snapshot = TeamTaskSnapshot(
            id=task_id,
            revision=1,
            subject=subject,
            description=description,
            status=initial_status,
            owner_id=owner_id,
            owner_name=owner_name,
            blocked_by=clean_blocked_by,
            write_scopes=tuple(w.strip() for w in write_scopes if w.strip()),
            created_at=now,
            updated_at=now,
        )
        self._tasks[task_id] = snapshot
        return self._build_view(snapshot)

    def get_task(self, task_id: str) -> TeamTaskView:
        snapshot = self._tasks.get(task_id)
        if snapshot is None:
            raise KeyError(f"Task {task_id} not found in team {self.team_id}")
        return self._build_view(snapshot)

    def list_tasks(self, include_deleted: bool = False) -> list[TeamTaskView]:
        tasks: list[TeamTaskView] = []
        for snapshot in self._tasks.values():
            if not include_deleted and snapshot.status == TeamTaskStatus.DELETED:
                continue
            tasks.append(self._build_view(snapshot))
        return tasks

    def update_task(
        self,
        task_id: str,
        expected_revision: int,
        subject: str | None = None,
        description: str | None = None,
        status: TeamTaskStatus | None = None,
        owner_id: str | None = None,
        owner_name: str | None = None,
        blocked_by: Sequence[str] | None = None,
        write_scopes: Sequence[str] | None = None,
    ) -> TeamTaskView:
        """Update a task guarded by CAS revision check."""
        current = self._tasks.get(task_id)
        if current is None:
            raise KeyError(f"Task {task_id} not found in team {self.team_id}")

        if current.revision != expected_revision:
            raise CASConflictError(task_id, expected_revision, current.revision)

        new_blocked_by = current.blocked_by
        if blocked_by is not None:
            clean_deps = tuple(b.strip() for b in blocked_by if b.strip())
            self._validate_dependencies(task_id, clean_deps)
            new_blocked_by = clean_deps

        new_write_scopes = current.write_scopes
        if write_scopes is not None:
            new_write_scopes = tuple(w.strip() for w in write_scopes if w.strip())

        now = time.time()
        updated = TeamTaskSnapshot(
            id=current.id,
            revision=current.revision + 1,
            subject=subject if subject is not None else current.subject,
            description=description if description is not None else current.description,
            status=status if status is not None else current.status,
            owner_id=owner_id if owner_id is not None else current.owner_id,
            owner_name=owner_name if owner_name is not None else current.owner_name,
            blocked_by=new_blocked_by,
            write_scopes=new_write_scopes,
            created_at=current.created_at,
            updated_at=now,
        )
        self._tasks[task_id] = updated
        return self._build_view(updated)

    def claim_task(
        self,
        task_id: str,
        expected_revision: int,
        owner_id: str,
        owner_name: str,
    ) -> TeamTaskView:
        """Claim an unowned, ready task using CAS."""
        current = self._tasks.get(task_id)
        if current is None:
            raise KeyError(f"Task {task_id} not found in team {self.team_id}")

        if current.revision != expected_revision:
            raise CASConflictError(task_id, expected_revision, current.revision)

        unmet = self._get_unmet_blockers(current)
        if unmet:
            raise TaskBlockedError(task_id, unmet)

        now = time.time()
        claimed = TeamTaskSnapshot(
            id=current.id,
            revision=current.revision + 1,
            subject=current.subject,
            description=current.description,
            status=TeamTaskStatus.IN_PROGRESS,
            owner_id=owner_id,
            owner_name=owner_name,
            blocked_by=current.blocked_by,
            write_scopes=current.write_scopes,
            created_at=current.created_at,
            updated_at=now,
        )
        self._tasks[task_id] = claimed
        return self._build_view(claimed)

    def complete_task(self, task_id: str, expected_revision: int) -> TeamTaskView:
        """Mark a task as completed using CAS."""
        return self.update_task(
            task_id=task_id,
            expected_revision=expected_revision,
            status=TeamTaskStatus.COMPLETED,
        )

    def delete_task(self, task_id: str, expected_revision: int) -> TeamTaskView:
        """Tombstone delete a task using CAS."""
        return self.update_task(
            task_id=task_id,
            expected_revision=expected_revision,
            status=TeamTaskStatus.DELETED,
        )

    # -------------------------------------------------------------------------
    # Internal DAG Validation and View Enrichment
    # -------------------------------------------------------------------------

    def _get_unmet_blockers(self, task: TeamTaskSnapshot) -> list[str]:
        unmet: list[str] = []
        for blocker_id in task.blocked_by:
            blocker = self._tasks.get(blocker_id)
            if blocker is None or blocker.status != TeamTaskStatus.COMPLETED:
                unmet.append(blocker_id)
        return unmet

    def _validate_dependencies(self, task_id: str, proposed_blockers: Sequence[str]) -> None:
        """Check for cycle in dependency graph."""
        if task_id in proposed_blockers:
            raise TaskDependencyCycleError(task_id, [task_id, task_id])

        # Graph DFS cycle detection
        adj: dict[str, list[str]] = {
            t_id: list(t.blocked_by)
            for t_id, t in self._tasks.items()
            if t.status != TeamTaskStatus.DELETED
        }
        adj[task_id] = list(proposed_blockers)

        visited: set[str] = set()
        recursion_stack: list[str] = []

        def dfs(node: str) -> None:
            visited.add(node)
            recursion_stack.append(node)
            for neighbor in adj.get(node, []):
                if neighbor not in visited:
                    dfs(neighbor)
                elif neighbor in recursion_stack:
                    cycle_start = recursion_stack.index(neighbor)
                    cycle = [*recursion_stack[cycle_start:], neighbor]
                    raise TaskDependencyCycleError(task_id, cycle)
            recursion_stack.pop()

        for node in list(adj.keys()):
            if node not in visited:
                dfs(node)

    def _compute_write_scope_warnings(self, current: TeamTaskSnapshot) -> tuple[str, ...]:
        """Advisory warning if multiple in-progress tasks overlap write scopes."""
        if not current.write_scopes or current.status != TeamTaskStatus.IN_PROGRESS:
            return ()

        warnings: list[str] = []
        for other in self._tasks.values():
            if other.id == current.id or other.status != TeamTaskStatus.IN_PROGRESS:
                continue
            for curr_scope in current.write_scopes:
                for other_scope in other.write_scopes:
                    if curr_scope.startswith(other_scope) or other_scope.startswith(curr_scope):
                        warnings.append(
                            f"Write scope conflict between task {current.id} ({curr_scope}) "
                            f"and task {other.id} ({other_scope})"
                        )
        return tuple(warnings)

    def _build_view(self, snapshot: TeamTaskSnapshot) -> TeamTaskView:
        unmet = self._get_unmet_blockers(snapshot)
        ready = (
            len(unmet) == 0
            and snapshot.status in (TeamTaskStatus.PENDING, TeamTaskStatus.IN_PROGRESS)
        )
        warnings = self._compute_write_scope_warnings(snapshot)

        return TeamTaskView(
            id=snapshot.id,
            revision=snapshot.revision,
            subject=snapshot.subject,
            description=snapshot.description,
            status=snapshot.status,
            owner_id=snapshot.owner_id,
            owner_name=snapshot.owner_name,
            blocked_by=snapshot.blocked_by,
            write_scopes=snapshot.write_scopes,
            ready=ready,
            write_scope_warnings=warnings,
        )
