"""Session Task State Machine and Compaction-Immune Task HUD Injection Engine.

[INPUT]
- Standard dataclasses and typing primitives

[OUTPUT]
- TaskStatus, TaskItem, SessionTaskState, format_compaction_immune_task_hud

[POS]
Maintains state-isolated task queue independent of LLM message history.
Ensures task checklist survives Context Compaction and hot reload (/reload).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal

TaskStatus = Literal["pending", "in_progress", "completed", "failed"]


@dataclass
class TaskItem:
    """Individual atomic step or task in the session task state."""

    id: str
    title: str
    status: TaskStatus = "pending"
    progress_percent: int = 0
    details: str = ""
    created_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    updated_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

    def to_dict(self) -> dict[str, str | int]:
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "progress_percent": self.progress_percent,
            "details": self.details,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class SessionTaskState:
    """State-isolated task machine for an agent conversation session."""

    session_id: str
    tasks: list[TaskItem] = field(default_factory=list)
    updated_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

    def add_task(
        self,
        task_id: str,
        title: str,
        details: str = "",
        status: TaskStatus = "pending",
        progress_percent: int = 0,
    ) -> TaskItem:
        """Add a new task item into the session task list."""
        # Avoid duplicate IDs
        for t in self.tasks:
            if t.id == task_id:
                t.title = title
                t.details = details
                t.status = status
                t.progress_percent = progress_percent
                t.updated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                self._touch()
                return t

        item = TaskItem(
            id=task_id,
            title=title,
            status=status,
            progress_percent=progress_percent,
            details=details,
        )
        self.tasks.append(item)
        self._touch()
        return item

    def update_task_status(
        self,
        task_id: str,
        status: TaskStatus,
        progress_percent: int | None = None,
        details: str | None = None,
    ) -> TaskItem | None:
        """Update the execution status or progress of an existing task."""
        for t in self.tasks:
            if t.id == task_id:
                t.status = status
                if progress_percent is not None:
                    t.progress_percent = max(0, min(100, progress_percent))
                elif status == "completed":
                    t.progress_percent = 100
                elif status == "in_progress" and t.progress_percent == 0:
                    t.progress_percent = 50

                if details is not None:
                    t.details = details
                t.updated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                self._touch()
                return t
        return None

    def remove_task(self, task_id: str) -> bool:
        """Remove a task from the session task list."""
        initial_len = len(self.tasks)
        self.tasks = [t for t in self.tasks if t.id != task_id]
        if len(self.tasks) < initial_len:
            self._touch()
            return True
        return False

    def get_active_task(self) -> TaskItem | None:
        """Return the currently running task, or the first pending task."""
        for t in self.tasks:
            if t.status == "in_progress":
                return t
        for t in self.tasks:
            if t.status == "pending":
                return t
        return None

    def calculate_overall_progress(self) -> int:
        """Calculate weighted completion percentage across all tasks."""
        if not self.tasks:
            return 0
        total = sum(t.progress_percent for t in self.tasks)
        return int(total / len(self.tasks))

    def to_dict(self) -> dict[str, str | list[dict[str, str | int]] | int]:
        return {
            "session_id": self.session_id,
            "tasks": [t.to_dict() for t in self.tasks],
            "overall_progress": self.calculate_overall_progress(),
            "updated_at": self.updated_at,
        }

    def _touch(self) -> None:
        self.updated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def format_compaction_immune_task_hud(state: SessionTaskState) -> str:
    """Generate persistent Task HUD context injection string for model prompts.

    This block is guaranteed to be injected into system/context memory verbatim,
    ensuring tasks are NEVER degraded or lost during Context Compaction.
    """
    if not state.tasks:
        return ""

    lines: list[str] = [
        "<!-- ANTI-COMPACTION PERSISTENT TASK HUD [IMMUNE TO DISTILLATION] -->",
        f"### ACTIVE TASK HUD [Session: {state.session_id} | Overall Progress: {state.calculate_overall_progress()}%]",
    ]

    for idx, t in enumerate(state.tasks, 1):
        status_marker = {
            "completed": "[x] COMPLETED",
            "in_progress": "[-] IN PROGRESS",
            "failed": "[!] FAILED",
            "pending": "[ ] PENDING",
        }.get(t.status, "[ ] PENDING")

        line = f"{idx}. {status_marker} ({t.progress_percent}%): {t.title}"
        if t.details:
            line += f" -- {t.details}"
        lines.append(line)

    lines.append("<!-- END TASK HUD -->")
    return "\n".join(lines)
