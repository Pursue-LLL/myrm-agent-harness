"""Data models for Structured Task State Machine and Compaction Preservation."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class TaskStepStatus(StrEnum):
    """Execution status of an individual task workflow step."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"


class TaskStepItem(BaseModel):
    """Discrete step within a multi-turn task workflow."""

    step_id: str = Field(description="Unique step identifier")
    title: str = Field(description="Actionable step description")
    status: TaskStepStatus = Field(default=TaskStepStatus.PENDING, description="Execution status")
    output_summary: str | None = Field(default=None, description="Artifact or execution outcome")
    started_at: datetime | None = Field(default=None, description="Step commencement timestamp")
    completed_at: datetime | None = Field(default=None, description="Step completion timestamp")


class TaskTodoItem(BaseModel):
    """Pending or resolved work item tracking open commitments."""

    todo_id: str = Field(description="Unique todo item identifier")
    description: str = Field(description="Requirement or pending subtask")
    is_resolved: bool = Field(default=False, description="Whether the todo has been addressed")
    priority: str = Field(default="normal", description="Priority tier: high, normal, low")
    resolution_note: str | None = Field(default=None, description="Details explaining resolution")


class StructuredTaskState(BaseModel):
    """High-privilege structured task container anchored against context compaction loss."""

    task_id: str = Field(description="Unique root task identifier")
    session_id: str = Field(description="Active session or conversation identifier")
    current_goal: str = Field(description="Overarching primary task objective")
    current_phase: str = Field(default="planning", description="Current workflow lifecycle phase")
    completed_steps: list[TaskStepItem] = Field(
        default_factory=list,
        description="Immutable sequence of finished execution steps",
    )
    active_steps: list[TaskStepItem] = Field(
        default_factory=list,
        description="Steps currently underway or pending resolution",
    )
    todos: list[TaskTodoItem] = Field(
        default_factory=list,
        description="Checklist of verified requirements and remaining items",
    )
    blockers: list[str] = Field(
        default_factory=list,
        description="Active blockers or waiting-on conditions",
    )
    metadata: dict[str, str] = Field(
        default_factory=dict,
        description="Domain-specific key-value flags",
    )
    version: int = Field(default=1, ge=1, description="Monotonically increasing state version")
    updated_at: datetime = Field(description="Timestamp of last state modification")


class CompactionAnchorPayload(BaseModel):
    """Compound context payload guaranteeing structured task state retention through compaction."""

    session_id: str = Field(description="Governed session identifier")
    raw_summary: str = Field(description="Natural language rolling compaction summary")
    structured_state: StructuredTaskState = Field(
        description="Authoritative structured state preserved intact",
    )
    anchor_text: str = Field(description="Formatted prompt injection block containing state anchor")
