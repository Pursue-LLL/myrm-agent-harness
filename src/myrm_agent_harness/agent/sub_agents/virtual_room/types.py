"""Core types for Multi-Human Multi-Agent Collaborative Virtual Room (Item 59).

[INPUT]
- Room membership declarations, filesystem lock leases, borrowing authorizations,
  and sandbox service port relay metadata.

[OUTPUT]
- Strongly-typed models supporting identity-execution-workspace tri-partitioning,
  fine-grained filesystem in-flight conflict locks, zero-credential agent borrowing,
  and live preview port relays.

[POS]
- Harness framework foundation for Tutti-style collaborative multi-human multi-agent co-dev.
"""

from __future__ import annotations

import enum
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field


class ParticipantRoleEnum(enum.StrEnum):
    """Role classification of participants within a collaborative virtual room."""

    HUMAN_DEV = "human_dev"
    AGENT_WORKER = "agent_worker"
    AGENT_REVIEWER = "agent_reviewer"
    AGENT_ARCHITECT = "agent_architect"


class LockScopeEnum(enum.StrEnum):
    """Granularity scope of a collaborative filesystem lease lock."""

    FILE_FULL = "file_full"
    LINE_RANGE = "line_range"
    AST_BLOCK = "ast_block"


class BorrowingGrantStatusEnum(enum.StrEnum):
    """Lifecycle state of an agent capability borrowing grant."""

    ACTIVE = "active"
    REVOKED = "revoked"
    EXPIRED = "expired"
    EXHAUSTED = "exhausted"


@dataclass(frozen=True)
class VirtualRoomParticipant:
    """Participant (human or AI agent) co-existing in a shared virtual room."""

    participant_id: str
    name: str
    role: ParticipantRoleEnum
    local_identity_bound: bool = True
    is_active: bool = True
    joined_at: float = 0.0


@dataclass(frozen=True)
class FileBlockLeaseLock:
    """Fine-grained file block lease lock coordinating in-flight writes without Git branches."""

    lock_id: str
    file_path: str
    holder_id: str
    holder_role: ParticipantRoleEnum
    scope: LockScopeEnum
    start_line: int | None = None
    end_line: int | None = None
    acquired_at: float = 0.0
    expires_at: float = 0.0
    ttl_seconds: float = 15.0


@dataclass(frozen=True)
class AgentBorrowingGrant:
    """Zero-credential capability delegation grant allowing teammates to borrow an Agent."""

    grant_id: str
    room_id: str
    owner_id: str
    borrower_id: str
    target_agent_model: str
    quota_tokens: int
    used_tokens: int = 0
    status: BorrowingGrantStatusEnum = BorrowingGrantStatusEnum.ACTIVE
    expires_at: float = 0.0


@dataclass(frozen=True)
class RoomServicePortRelay:
    """Live port relay exposing a sandbox-hosted web service across the entire room."""

    relay_id: str
    room_id: str
    service_name: str
    port: int
    live_preview_url: str
    launched_by_id: str
    is_healthy: bool = True
    created_at: float = 0.0


@dataclass(frozen=True)
class VirtualRoomActivityEvent:
    """Persistent audit log entry capturing collaborative actions within a room."""

    event_id: str
    room_id: str
    actor_id: str
    event_type: str
    details: Mapping[str, str | int | float | bool] = field(default_factory=dict)
    timestamp: float = 0.0


@dataclass(frozen=True)
class VirtualRoomState:
    """Snapshot representation of an active collaborative virtual room."""

    room_id: str
    name: str
    participants: Sequence[VirtualRoomParticipant] = field(default_factory=tuple)
    active_locks: Sequence[FileBlockLeaseLock] = field(default_factory=tuple)
    borrowing_grants: Sequence[AgentBorrowingGrant] = field(default_factory=tuple)
    service_relays: Sequence[RoomServicePortRelay] = field(default_factory=tuple)
    created_at: float = 0.0
    last_activity_at: float = 0.0
