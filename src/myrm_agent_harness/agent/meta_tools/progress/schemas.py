"""Progress todo schemas — SSOT for main-agent multi-step tracking.

[INPUT]
- pydantic::BaseModel (POS: validation)

[OUTPUT]
- TodoStatus, TodoItem, TodoStore: workspace todo models
- plan-compat helpers for Goal API hydration

[POS]
Data models for `.myrm/progress/todos.json` SSOT and server plan endpoint.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class TodoStatus(StrEnum):
    """Lifecycle states for a single todo item."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TodoItem(BaseModel):
    """One actionable step in a multi-step session."""

    id: str
    content: str
    status: TodoStatus = TodoStatus.PENDING


class TodoStore(BaseModel):
    """Workspace-persisted todo list for the current chat session."""

    goal: str | None = None
    todos: list[TodoItem] = Field(default_factory=list)

    def incomplete_todos(self) -> list[TodoItem]:
        return [item for item in self.todos if item.status not in (TodoStatus.COMPLETED, TodoStatus.CANCELLED)]

    def to_plan_compat(self) -> dict[str, object]:
        """Shape compatible with legacy Goal plan API consumers."""
        return {
            "goal": self.goal or "Task progress",
            "reasoning": "",
            "steps": [
                {
                    "step_id": item.id,
                    "description": item.content,
                    "expected_output": "",
                    "status": _todo_status_to_plan_status(item.status),
                }
                for item in self.todos
            ],
        }


def _todo_status_to_plan_status(status: TodoStatus) -> str:
    if status == TodoStatus.IN_PROGRESS:
        return "in_progress"
    if status == TodoStatus.COMPLETED:
        return "completed"
    if status == TodoStatus.CANCELLED:
        return "skipped"
    return "pending"
