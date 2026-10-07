from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class StepExecutionStatus(StrEnum):
    """Execution status for a single plan/progress step."""

    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"
    SKIPPED = "SKIPPED"


class ProgressStep(BaseModel):
    """Single step in the task progress lifecycle."""

    model_config = ConfigDict(frozen=True)

    step_index: int = Field(..., ge=0, description="0-indexed or 1-indexed sequential step number")
    description: str = Field(..., description="Actionable title or explanation of the step")
    status: StepExecutionStatus = Field(default=StepExecutionStatus.PENDING, description="Current progress status")
    notes: str | None = Field(default=None, description="Optional extra notes or artifacts produced")


class WorkNotesSnapshot(BaseModel):
    """In-memory or serialized state of agent work notes and execution progress."""

    model_config = ConfigDict(frozen=True)

    goal: str = Field(..., description="Primary mission or objective")
    current_step_index: int = Field(default=0, ge=0, description="Active working step index")
    steps: list[ProgressStep] = Field(default_factory=list, description="Ordered execution step plan")
    key_findings: list[str] = Field(default_factory=list, description="Critical findings and validated hypotheses")
    disqualified_approaches: list[str] = Field(
        default_factory=list, description="Rejected or failed solution patterns to avoid repetition"
    )
    todos: list[str] = Field(default_factory=list, description="Remaining actionable checklist items")
    last_synced_hash: str | None = Field(
        default=None, description="Composite SHA-256 hash of WORK_NOTES.md and PROGRESS.md"
    )
    updated_at_iso: str | None = Field(default=None, description="ISO timestamp of last update")


class SyncDirection(StrEnum):
    """Direction of the notes/progress synchronization."""

    AGENT_TO_WORKSPACE = "AGENT_TO_WORKSPACE"
    WORKSPACE_TO_AGENT = "WORKSPACE_TO_AGENT"
    IN_SYNC = "IN_SYNC"


class HumanInterventionDiff(BaseModel):
    """Represents differences detected when human edits WORK_NOTES.md or PROGRESS.md externally."""

    model_config = ConfigDict(frozen=True)

    modified: bool = Field(default=False, description="Whether human changes were detected")
    modified_files: list[str] = Field(default_factory=list, description="Files with manual edits detected")
    updated_goal: str | None = Field(default=None, description="Modified goal if altered by user")
    steps_completed_by_human: list[int] = Field(
        default_factory=list, description="Indices of steps checked off externally by human"
    )
    new_todos_added: list[str] = Field(default_factory=list, description="New todos manually appended by human")
    new_findings_added: list[str] = Field(
        default_factory=list, description="New findings or constraints added by human"
    )


class SyncResult(BaseModel):
    """Outcome of a synchronization operation."""

    model_config = ConfigDict(frozen=True)

    direction: SyncDirection = Field(..., description="Direction of sync performed")
    success: bool = Field(default=True, description="Whether synchronization succeeded")
    snapshot: WorkNotesSnapshot = Field(..., description="Resulting consolidated snapshot")
    intervention_diff: HumanInterventionDiff | None = Field(
        default=None, description="Diff details if human intervention occurred"
    )
    message: str = Field(default="", description="Diagnostic status message")
