"""Project milestone tracker managing multi-phase project checkpoints.

Maintains committed architectural decisions, dependent TODO topologies,
and incremental material delta histories across long-horizon sessions.

[INPUT]
- runtime.context.project_milestone_types::IncrementalMaterialUpdate, MilestoneDecisionRecord,
  MilestonePhaseKind, ProjectMilestoneCheckpoint, ProjectTodoItem (POS: Data contracts for long-horizon
  project milestone checkpoints and resumption.)

[OUTPUT]
- ProjectMilestoneTracker: State machine governing project-level milestones and continuous state.

[POS]
Project milestone tracker managing multi-phase project checkpoints.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Sequence

from myrm_agent_harness.runtime.context.project_milestone_types import (
    IncrementalMaterialUpdate,
    MilestoneDecisionRecord,
    MilestonePhaseKind,
    ProjectMilestoneCheckpoint,
    ProjectTodoItem,
)


class ProjectMilestoneTracker:
    """State machine governing project-level milestones and continuous state."""

    def __init__(self) -> None:
        self._checkpoints: dict[str, list[ProjectMilestoneCheckpoint]] = {}
        self._active_decisions: dict[str, list[MilestoneDecisionRecord]] = {}
        self._todos: dict[str, list[ProjectTodoItem]] = {}
        self._deliverables: dict[str, list[str]] = {}
        self._materials: dict[str, list[IncrementalMaterialUpdate]] = {}
        self._completed_milestones: dict[str, list[str]] = {}
        self._current_phase: dict[str, MilestonePhaseKind] = {}

    def init_project(
        self,
        project_id: str,
        initial_phase: MilestonePhaseKind = MilestonePhaseKind.REQUIREMENTS_ANALYSIS,
        metadata: dict[str, str] | None = None,
    ) -> ProjectMilestoneCheckpoint:
        """Initialize continuous state tracking for a new long-horizon project."""
        self._current_phase[project_id] = initial_phase
        self._active_decisions.setdefault(project_id, [])
        self._todos.setdefault(project_id, [])
        self._deliverables.setdefault(project_id, [])
        self._materials.setdefault(project_id, [])
        self._completed_milestones.setdefault(project_id, [])

        ckpt = self._snapshot_checkpoint(project_id, metadata=metadata or {})
        self._checkpoints.setdefault(project_id, []).append(ckpt)
        return ckpt

    def advance_phase(
        self,
        project_id: str,
        new_phase: MilestonePhaseKind,
        milestone_title: str,
        metadata: dict[str, str] | None = None,
    ) -> ProjectMilestoneCheckpoint:
        """Advance the project to a subsequent lifecycle phase, sealing a milestone."""
        self._current_phase[project_id] = new_phase
        self._completed_milestones.setdefault(project_id, []).append(milestone_title)

        ckpt = self._snapshot_checkpoint(project_id, metadata=metadata or {})
        self._checkpoints.setdefault(project_id, []).append(ckpt)
        return ckpt

    def record_decision(
        self,
        project_id: str,
        title: str,
        rationale: str,
    ) -> MilestoneDecisionRecord:
        """Commit an immutable decision record to the project registry."""
        record = MilestoneDecisionRecord(
            decision_id=f"dec_{uuid.uuid4().hex[:8]}",
            title=title,
            rationale=rationale,
            accepted_at=time.time(),
            status="active",
        )
        self._active_decisions.setdefault(project_id, []).append(record)
        return record

    def add_todo(
        self,
        project_id: str,
        todo_id: str,
        title: str,
        depends_on: Sequence[str] = (),
        priority: str = "normal",
    ) -> ProjectTodoItem:
        """Append a pending action item with explicit dependency linkages."""
        item = ProjectTodoItem(
            todo_id=todo_id,
            title=title,
            status="pending",
            depends_on=tuple(depends_on),
            priority=priority,
        )
        todo_list = self._todos.setdefault(project_id, [])
        # Replace if ID exists, else append
        self._todos[project_id] = [t for t in todo_list if t.todo_id != todo_id] + [item]
        return item

    def resolve_todo(self, project_id: str, todo_id: str) -> bool:
        """Mark a pending action item as resolved."""
        todo_list = self._todos.get(project_id, [])
        updated = False
        new_list: list[ProjectTodoItem] = []
        for item in todo_list:
            if item.todo_id == todo_id:
                new_list.append(
                    ProjectTodoItem(
                        todo_id=item.todo_id,
                        title=item.title,
                        status="resolved",
                        depends_on=item.depends_on,
                        priority=item.priority,
                    )
                )
                updated = True
            else:
                new_list.append(item)
        if updated:
            self._todos[project_id] = new_list
        return updated

    def register_deliverables(
        self, project_id: str, file_paths: Sequence[str]
    ) -> None:
        """Register newly verified artifact files produced by the agent."""
        existing = set(self._deliverables.setdefault(project_id, []))
        for p in file_paths:
            if p not in existing:
                existing.add(p)
                self._deliverables[project_id].append(p)

    def attach_material_update(
        self, project_id: str, update: IncrementalMaterialUpdate
    ) -> None:
        """Append an extracted incremental material update to the project log."""
        self._materials.setdefault(project_id, []).append(update)

    def compute_ready_todos(self, project_id: str) -> tuple[str, ...]:
        """Compute pending TODO IDs whose dependencies have all been satisfied/resolved."""
        items = self._todos.get(project_id, [])
        resolved_ids = {item.todo_id for item in items if item.status == "resolved"}

        ready: list[str] = []
        for item in items:
            if item.status == "pending" and all(
                dep in resolved_ids for dep in item.depends_on
            ):
                ready.append(item.todo_id)
        return tuple(ready)

    def snapshot_checkpoint(
        self, project_id: str, metadata: dict[str, str] | None = None
    ) -> ProjectMilestoneCheckpoint:
        """Explicitly capture and persist a milestone checkpoint snapshot."""
        ckpt = self._snapshot_checkpoint(project_id, metadata=metadata or {})
        self._checkpoints.setdefault(project_id, []).append(ckpt)
        return ckpt

    def get_latest_milestone(
        self, project_id: str
    ) -> ProjectMilestoneCheckpoint | None:
        """Retrieve the latest checkpoint snapshot for the project reflecting real-time state."""
        if project_id not in self._current_phase:
            return None
        return self._snapshot_checkpoint(project_id)

    def list_milestone_history(
        self, project_id: str
    ) -> tuple[ProjectMilestoneCheckpoint, ...]:
        """Return the complete sequence of milestone checkpoints for the project."""
        return tuple(self._checkpoints.get(project_id, []))

    def _snapshot_checkpoint(
        self, project_id: str, metadata: dict[str, str] | None = None
    ) -> ProjectMilestoneCheckpoint:
        """Construct an immutable milestone checkpoint snapshot from current state."""
        phase = self._current_phase.get(
            project_id, MilestonePhaseKind.REQUIREMENTS_ANALYSIS
        )
        return ProjectMilestoneCheckpoint(
            checkpoint_id=f"mlp_{uuid.uuid4().hex[:10]}",
            project_id=project_id,
            phase=phase,
            completed_milestones=tuple(self._completed_milestones.get(project_id, [])),
            active_decisions=tuple(self._active_decisions.get(project_id, [])),
            pending_todos=tuple(self._todos.get(project_id, [])),
            deliverable_files=tuple(self._deliverables.get(project_id, [])),
            material_history=tuple(self._materials.get(project_id, [])),
            timestamp=time.time(),
            metadata=dict(metadata or {}),
        )

