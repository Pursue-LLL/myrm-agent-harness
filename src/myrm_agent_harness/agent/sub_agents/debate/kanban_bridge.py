"""[INPUT] types.py (DebateSubtask, DebateSubtaskStatus, DebateRole).
[OUTPUT] DebateKanbanBridge: Bidirectional state mapping and task payload builder between Debate Workroom and Kanban.
[POS] Bridge adapter decoupling debate subtasks from the server/harness Kanban subsystems.
"""

from __future__ import annotations

from typing import ClassVar

from myrm_agent_harness.agent.sub_agents.debate.types import (
    DebateSubtask,
    DebateSubtaskStatus,
)


class DebateKanbanBridge:
    """Bidirectional state mapping and task payload synchronization bridge."""

    _DEBATE_TO_KANBAN_STATUS: ClassVar[dict[DebateSubtaskStatus, str]] = {
        DebateSubtaskStatus.TODO: "READY",
        DebateSubtaskStatus.IN_PROGRESS: "RUNNING",
        DebateSubtaskStatus.BLOCKED: "BLOCKED",
        DebateSubtaskStatus.IN_REVIEW: "IN_REVIEW",
        DebateSubtaskStatus.DONE: "COMPLETED",
    }

    _KANBAN_TO_DEBATE_STATUS: ClassVar[dict[str, DebateSubtaskStatus]] = {
        "TRIAGE": DebateSubtaskStatus.TODO,
        "BACKLOG": DebateSubtaskStatus.TODO,
        "READY": DebateSubtaskStatus.TODO,
        "RUNNING": DebateSubtaskStatus.IN_PROGRESS,
        "BLOCKED": DebateSubtaskStatus.BLOCKED,
        "IN_REVIEW": DebateSubtaskStatus.IN_REVIEW,
        "COMPLETED": DebateSubtaskStatus.DONE,
        "FAILED": DebateSubtaskStatus.BLOCKED,
        "ARCHIVED": DebateSubtaskStatus.DONE,
    }

    @classmethod
    def to_kanban_status(cls, status: DebateSubtaskStatus) -> str:
        """Map debate subtask status to Kanban task status."""
        return cls._DEBATE_TO_KANBAN_STATUS.get(status, "READY")

    @classmethod
    def to_debate_status(cls, kanban_status: str) -> DebateSubtaskStatus:
        """Map Kanban task status to debate subtask status."""
        normalized = kanban_status.upper().strip()
        return cls._KANBAN_TO_DEBATE_STATUS.get(normalized, DebateSubtaskStatus.TODO)

    @classmethod
    def build_kanban_task_payload(
        cls,
        room_id: str,
        subtask: DebateSubtask,
    ) -> dict[str, str | list[str] | dict[str, str]]:
        """Build a standardized Kanban task creation payload from a debate subtask."""
        return {
            "title": f"[{subtask.assigned_role.value.upper()}] {subtask.title}",
            "description": subtask.description,
            "assigned_agent_id": subtask.assigned_agent_id,
            "initial_status": cls.to_kanban_status(subtask.status),
            "tags": ["debate-workroom", f"room:{room_id}", f"role:{subtask.assigned_role.value}"],
            "metadata": {
                "workroom_room_id": room_id,
                "subtask_id": subtask.task_id,
                "assigned_role": subtask.assigned_role.value,
            },
        }

    @classmethod
    def sync_subtask_with_kanban(
        cls,
        subtask: DebateSubtask,
        kanban_task_id: str,
        kanban_status: str | None = None,
    ) -> DebateSubtask:
        """Bind a kanban task id and optionally update the status from Kanban."""
        subtask.kanban_task_id = kanban_task_id
        if kanban_status is not None:
            subtask.status = cls.to_debate_status(kanban_status)
        return subtask
