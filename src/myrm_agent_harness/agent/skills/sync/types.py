"""Skill sync data types.

[INPUT]
- (none)

[OUTPUT]
- RemoteSkillEntry: Lightweight descriptor of a remote skill
- SyncDirection: Push / Pull direction enum
- PushResult: Result of pushing skills to shared repository
- PullResult: Result of pulling skills from shared repository
- GateVerdict: Quality gate evaluation result
- ConflictResolution: How a conflict was resolved

[POS]
Data types for the skill sync subsystem.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class SyncDirection(StrEnum):
    """Direction of a sync operation."""

    PUSH = "push"
    PULL = "pull"


class ConflictStrategy(StrEnum):
    """How to resolve version conflicts between local and remote."""

    REMOTE_WINS = "remote_wins"
    LOCAL_WINS = "local_wins"
    NEWER_WINS = "newer_wins"
    SKIP = "skip"


@dataclass(frozen=True, slots=True)
class RemoteSkillEntry:
    """Lightweight descriptor of a remote skill (no content, just metadata)."""

    name: str
    version: str
    content_sha256: str
    description: str = ""
    updated_at: datetime | None = None
    author: str = ""
    tags: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class GateVerdict:
    """Result of quality gate evaluation."""

    passed: bool
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ConflictResolution:
    """How a conflict between local and remote skill versions was resolved."""

    skill_name: str
    strategy_used: ConflictStrategy
    winner_sha256: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class PushResult:
    """Result of pushing skills to a shared repository."""

    success: bool
    pushed_count: int = 0
    rejected_count: int = 0
    rejected_skills: list[str] = field(default_factory=list)
    gate_verdicts: dict[str, GateVerdict] = field(default_factory=dict)
    error: str = ""


@dataclass(frozen=True, slots=True)
class PullResult:
    """Result of pulling skills from a shared repository."""

    success: bool
    new_count: int = 0
    updated_count: int = 0
    conflict_count: int = 0
    conflicts: list[ConflictResolution] = field(default_factory=list)
    pulled_skills: list[str] = field(default_factory=list)
    error: str = ""


@dataclass(slots=True)
class SyncStatus:
    """Current sync status for UI display."""

    enabled: bool = False
    last_sync_at: datetime | None = None
    last_sync_direction: SyncDirection | None = None
    last_sync_result: str = ""
    pending_push_count: int = 0
    pending_pull_count: int = 0
    is_syncing: bool = False
