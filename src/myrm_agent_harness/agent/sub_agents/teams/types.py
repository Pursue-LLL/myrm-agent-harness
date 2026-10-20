"""Type definitions and models for Durable Agent Teams.

[INPUT]
- None (root types)

[OUTPUT]
- TeamMemberPhase, TeamMemberRole, TeamTaskStatus, DeliveryMode
- TeamMemberSnapshot, TeamMessageSnapshot, TeamTaskSnapshot, TeamTaskView, TeamProjection
- CASConflictError, TaskDependencyCycleError, TaskBlockedError

[POS]
Defines immutable data models and contracts for multi-agent durable teams,
CAS versioned task board DAG, and peer mailboxes.
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field


class TeamMemberPhase(enum.StrEnum):
    """Lifecycle phase of a durable team member."""

    PROVISIONING = "provisioning"
    ACTIVE = "active"
    FAILED = "failed"


class TeamMemberRole(enum.StrEnum):
    """Role within the team."""

    LEAD = "lead"
    TEAMMATE = "teammate"


class TeamTaskStatus(enum.StrEnum):
    """Status of a task on the shared task board."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    DELETED = "deleted"


class DeliveryMode(enum.StrEnum):
    """Peer mailbox delivery mode."""

    QUIET = "quiet"
    WAKING = "waking"


class CASConflictError(Exception):
    """Raised when expectedRevision does not match current task revision."""

    def __init__(self, task_id: str, expected: int, actual: int) -> None:
        super().__init__(
            f"CAS conflict on task {task_id}: expected revision {expected}, but current is {actual}"
        )
        self.task_id = task_id
        self.expected = expected
        self.actual = actual


class TaskDependencyCycleError(Exception):
    """Raised when a task dependency creates a directed cycle."""

    def __init__(self, task_id: str, cycle_path: list[str]) -> None:
        cycle_str = " -> ".join(cycle_path)
        super().__init__(f"Dependency cycle detected for task {task_id}: {cycle_str}")
        self.task_id = task_id
        self.cycle_path = cycle_path


class TaskBlockedError(Exception):
    """Raised when claiming or starting a task whose blockers are incomplete."""

    def __init__(self, task_id: str, unmet_blockers: list[str]) -> None:
        blockers_str = ", ".join(unmet_blockers)
        super().__init__(
            f"Cannot claim task {task_id}: blocked by incomplete tasks [{blockers_str}]"
        )
        self.task_id = task_id
        self.unmet_blockers = unmet_blockers


@dataclass(frozen=True, slots=True)
class TeamMemberSnapshot:
    """Whole durable value written on every teammate lifecycle change."""

    id: str
    name: str
    description: str
    provider: str
    context: str  # "fresh" | "fork"
    role: TeamMemberRole
    phase: TeamMemberPhase
    error: str | None = None
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, str | float | None]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "provider": self.provider,
            "context": self.context,
            "role": self.role.value,
            "phase": self.phase.value,
            "error": self.error,
            "created_at": self.created_at,
        }


@dataclass(frozen=True, slots=True)
class TeamMessageSnapshot:
    """One peer message recorded by the durable Team mailbox."""

    id: str
    team_id: str
    sender_id: str
    sender_name: str
    target_id: str
    target_name: str
    content: str
    mode: DeliveryMode = DeliveryMode.QUIET
    created_at: float = field(default_factory=time.time)
    delivered: bool = False

    def to_dict(self) -> dict[str, str | bool | float]:
        return {
            "id": self.id,
            "team_id": self.team_id,
            "sender_id": self.sender_id,
            "sender_name": self.sender_name,
            "target_id": self.target_id,
            "target_name": self.target_name,
            "content": self.content,
            "mode": self.mode.value,
            "created_at": self.created_at,
            "delivered": self.delivered,
        }


@dataclass(frozen=True, slots=True)
class TeamTaskSnapshot:
    """Whole durable task snapshot; mutations increment revision."""

    id: str
    revision: int
    subject: str
    description: str
    status: TeamTaskStatus
    owner_id: str | None = None
    owner_name: str | None = None
    blocked_by: tuple[str, ...] = ()
    write_scopes: tuple[str, ...] = ()
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, str | int | float | list[str] | None]:
        return {
            "id": self.id,
            "revision": self.revision,
            "subject": self.subject,
            "description": self.description,
            "status": self.status.value,
            "owner_id": self.owner_id,
            "owner_name": self.owner_name,
            "blocked_by": list(self.blocked_by),
            "write_scopes": list(self.write_scopes),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True, slots=True)
class TeamTaskView:
    """Runtime-enriched task view returned to tools, UI, and hosts."""

    id: str
    revision: int
    subject: str
    description: str
    status: TeamTaskStatus
    owner_id: str | None
    owner_name: str | None
    blocked_by: tuple[str, ...]
    write_scopes: tuple[str, ...]
    ready: bool
    write_scope_warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, str | int | bool | list[str] | None]:
        return {
            "id": self.id,
            "revision": self.revision,
            "subject": self.subject,
            "description": self.description,
            "status": self.status.value,
            "owner_id": self.owner_id,
            "owner_name": self.owner_name,
            "blocked_by": list(self.blocked_by),
            "write_scopes": list(self.write_scopes),
            "ready": self.ready,
            "write_scope_warnings": list(self.write_scope_warnings),
        }


@dataclass(frozen=True, slots=True)
class TeamProjection:
    """Durable Team state projection published to callers and web UI."""

    team_id: str
    members: tuple[TeamMemberSnapshot, ...]
    tasks: tuple[TeamTaskView, ...]
    failure: str | None = None

    def to_dict(self) -> dict[str, str | list[dict[str, object]] | None]:
        return {
            "team_id": self.team_id,
            "members": [m.to_dict() for m in self.members],
            "tasks": [t.to_dict() for t in self.tasks],
            "failure": self.failure,
        }
