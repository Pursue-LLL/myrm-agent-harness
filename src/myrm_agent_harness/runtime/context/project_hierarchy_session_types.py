"""Project hierarchy session archive and keyword resurrection types.

Defines the Project-Task-Session tree hierarchy, full-text search match models,
and seamless breakpoint resurrection bundles for long-horizon agent state recovery.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal


class HierarchyHitKind(StrEnum):
    """Discriminant kind for hierarchy search hits."""

    PROJECT = "project"
    TASK = "task"
    SESSION = "session"
    MESSAGE = "message"


class ResurrectionStatus(StrEnum):
    """Lifecycle status of resurrected agent session."""

    READY = "ready"
    HYDRATED = "hydrated"
    FAILED = "failed"


@dataclass(frozen=True)
class ProjectNode:
    """Project-level anchor node bound to workspace and repo."""

    project_id: str
    name: str
    description: str
    workspace_path: str
    repo_url: str = ""
    tags: tuple[str, ...] = ()
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class TaskNode:
    """Task-level intermediate grouping node under a project."""

    task_id: str
    project_id: str
    title: str
    description: str
    status: str = "open"  # "open" | "in_progress" | "resolved" | "closed"
    priority: str = "normal"  # "low" | "normal" | "high" | "urgent"
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class ArchivedMessageEntry:
    """Archived conversation message turn with keyword searchable fields."""

    message_id: str
    session_id: str
    role: Literal["user", "assistant", "system", "tool"]
    content: str
    tool_calls: tuple[str, ...] = ()
    error_traces: tuple[str, ...] = ()
    file_references: tuple[str, ...] = ()
    timestamp: float = 0.0


@dataclass(frozen=True)
class ArchivedSessionNode:
    """Session-level node belonging to a task within a project."""

    session_id: str
    task_id: str
    project_id: str
    title: str
    description: str
    agent_model: str
    status: str = "completed"  # "active" | "completed" | "archived" | "aborted"
    created_at: float = 0.0
    last_active: float = 0.0
    total_messages: int = 0
    total_tokens: int = 0
    tags: tuple[str, ...] = ()
    checkpoint_summary: str = ""


@dataclass(frozen=True)
class HierarchySearchHit:
    """Detailed hit record matching a search query."""

    kind: HierarchyHitKind
    id: str
    title: str
    snippet: str
    project_id: str
    task_id: str | None
    session_id: str | None
    score: float
    matched_fields: tuple[str, ...]


@dataclass(frozen=True)
class HierarchyGroupMatch:
    """Aggregated search group organizing matches by project and task."""

    project: ProjectNode
    matches: tuple[HierarchySearchHit, ...]
    total_matches: int
    best_score: float


@dataclass(frozen=True)
class HierarchySearchResult:
    """Global multi-dimensional search result across project hierarchies."""

    query: str
    total_hits: int
    groups: tuple[HierarchyGroupMatch, ...]
    is_truncated: bool


@dataclass(frozen=True)
class ResurrectionContextBundle:
    """Complete restored working state allowing seamless continuation of a historical agent."""

    session_id: str
    project: ProjectNode
    task: TaskNode
    session: ArchivedSessionNode
    messages: tuple[ArchivedMessageEntry, ...]
    resurrected_at: float
    status: ResurrectionStatus
    resurrection_prompt: str
    restored_tokens: int
