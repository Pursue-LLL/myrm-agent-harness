"""Core types and data contracts for Multi-Agent Visual Timeline & Cherry-Pick Rollback (Item 61).

[INPUT]
- Domain data models, dataclasses, and StrEnum specifications.

[OUTPUT]
- ActorType, OperationType, RollbackStatus,
  TimelineNode, RollbackResult, TimelineFilterCriteria.

[POS]
- Harness foundation for Item 61 collaborative visual timeline and surgical rollback.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class ActorType(StrEnum):
    """Classification of event initiator."""

    HUMAN_USER = "human_user"
    LOCAL_AGENT = "local_agent"
    CLOUD_AGENT = "cloud_agent"
    SYSTEM_ORCHESTRATOR = "system_orchestrator"


class OperationType(StrEnum):
    """Category of atomic mutation on the workspace/filesystem."""

    FILE_MODIFY = "file_modify"
    FILE_CREATE = "file_create"
    FILE_DELETE = "file_delete"
    TOOL_EXECUTION = "tool_execution"
    GIT_COMMIT = "git_commit"


class RollbackStatus(StrEnum):
    """Outcome status of an atomic cherry-pick rollback attempt."""

    SUCCESS = "success"
    CONFLICT_DETECTED = "conflict_detected"
    ALREADY_ROLLED_BACK = "already_rolled_back"
    NODE_NOT_FOUND = "node_not_found"


@dataclass(slots=True)
class TimelineNode:
    """An individual atomic timeline event recorded during multi-agent co-dev."""

    node_id: str
    session_id: str
    actor_id: str
    actor_name: str
    actor_type: ActorType
    operation_type: OperationType
    file_path: str
    line_start: int | None = None
    line_end: int | None = None
    before_content: str = ""
    after_content: str = ""
    diff_summary: str = ""
    parent_node_id: str | None = None
    is_rolled_back: bool = False
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class RollbackResult:
    """Outcome of attempting to revert a single agent's execution node."""

    node_id: str
    status: RollbackStatus
    file_path: str
    restored_content: str = ""
    conflict_reason: str | None = None
    rollback_timestamp: float = field(default_factory=time.time)


@dataclass(slots=True)
class TimelineFilterCriteria:
    """Multi-dimensional filtering parameters for activity timeline queries."""

    actor_id: str | None = None
    actor_type: ActorType | None = None
    file_path: str | None = None
    operation_type: OperationType | None = None
    start_time: float | None = None
    end_time: float | None = None
