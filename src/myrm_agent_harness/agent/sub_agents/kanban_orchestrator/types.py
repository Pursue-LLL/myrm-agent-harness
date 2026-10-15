"""Type definitions and domain models for Multi-Agent Kanban Orchestrator and Card Lifecycle Dispatcher."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class KanbanLaneEnum(StrEnum):
    """Kanban swimlane columns."""

    BACKLOG = "backlog"
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    REVIEW = "review"
    DONE = "done"
    BLOCKED = "blocked"


class CardPriorityEnum(StrEnum):
    """Task card priority rating."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class CardArtifactDTO(BaseModel):
    """Materialized artifact mounted to a Kanban card."""

    artifact_id: str = Field(..., description="Unique artifact ID")
    name: str = Field(..., description="Human-readable artifact title")
    artifact_type: str = Field(default="file", description="Artifact type (diff, file, report, test_result)")
    file_path: str | None = Field(default=None, description="Workspace file path")
    content_preview: str | None = Field(default=None, description="Brief content preview")
    mounted_at: float = Field(..., description="Timestamp of mounting")


class KanbanCardDTO(BaseModel):
    """Persistent task card in the multi-agent Kanban board."""

    card_id: str = Field(..., description="Unique card ID (e.g. card-api-8821)")
    board_id: str = Field(..., description="Associated board ID")
    title: str = Field(..., description="Task title")
    description: str = Field(default="", description="Detailed mission description")
    lane: KanbanLaneEnum = Field(default=KanbanLaneEnum.BACKLOG, description="Current swimlane column")
    priority: CardPriorityEnum = Field(default=CardPriorityEnum.MEDIUM, description="Task urgency level")
    assigned_agent: str = Field(..., description="Assigned specialist Agent handle (e.g. @backend-dev, @tester)")
    depends_on: list[str] = Field(default_factory=list, description="IDs of prerequisite cards that must be completed")
    blocked_by: list[str] = Field(default_factory=list, description="IDs of currently uncompleted dependencies")
    sandbox_subdir: str = Field(..., description="Card-scoped isolated directory (e.g. tasks/card-api-8821)")
    artifacts: list[CardArtifactDTO] = Field(default_factory=list, description="Mounted task artifacts")
    created_at: float = Field(..., description="Creation epoch timestamp")
    updated_at: float = Field(..., description="Last modification timestamp")
    completed_at: float | None = Field(default=None, description="Completion epoch timestamp")


class KanbanBoardStateDTO(BaseModel):
    """Full projection state of a multi-agent Kanban project board."""

    board_id: str = Field(..., description="Board identifier")
    session_id: str = Field(..., description="Parent chat or project session ID")
    title: str = Field(..., description="Project board name")
    cards: dict[str, KanbanCardDTO] = Field(default_factory=dict, description="Card lookup map by card_id")
    created_at: float = Field(..., description="Board creation epoch")
    updated_at: float = Field(..., description="Last board update epoch")


class KanbanDependencyCycleError(ValueError):
    """Raised when cyclic dependencies are detected in the card DAG."""


class KanbanCardNotFoundError(KeyError):
    """Raised when a referenced card ID does not exist."""


class InvalidKanbanTransitionError(ValueError):
    """Raised when attempting an illegal lane state transition."""


class KanbanBlockedCardError(PermissionError):
    """Raised when attempting to execute or complete a card blocked by unresolved dependencies."""
