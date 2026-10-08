"""Data types and models for Pre-Flight Irreversible Write Interception and Emergency Kill Switch."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


def _utc_now() -> datetime:
    """Return current UTC timestamp."""
    return datetime.now(UTC)


class WriteDomain(StrEnum):
    """Categorization of irreversible external write action domains."""

    EMAIL = "email"
    GIT_PUSH = "git_push"
    PAYMENT = "payment"
    DATABASE_WRITE = "database"
    IM_BROADCAST = "im_broadcast"


class InterceptionStatus(StrEnum):
    """Lifecycle status of a pre-flight intercepted write operation."""

    PENDING_CONFIRMATION = "pending_confirmation"
    APPROVED = "approved"
    KILLED_ABORTED = "killed_aborted"
    TIMED_OUT = "timed_out"


class RiskLevel(StrEnum):
    """Assessed explosion risk tier for blast radius visualization."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True, slots=True)
class BlastRadiusCard:
    """Explosion radius card presented to users before executing irreversible actions."""

    intent_id: str
    domain: WriteDomain
    title: str
    summary: str
    details: dict[str, str]
    risk_level: RiskLevel
    created_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class IrreversibleWriteContract:
    """Contract declaration identifying a tool as performing irreversible external write operations."""

    tool_name: str
    domain: WriteDomain
    description: str
    default_risk_level: RiskLevel = RiskLevel.HIGH


@dataclass(frozen=True, slots=True)
class IrreversibleWriteIntent:
    """Intercepted operation execution frame suspended awaiting blast radius review."""

    intent_id: str
    session_id: str
    tool_name: str
    domain: WriteDomain
    arguments: dict[str, str]
    blast_radius: BlastRadiusCard
    status: InterceptionStatus = InterceptionStatus.PENDING_CONFIRMATION
    resolution_reason: str = ""
    created_at: datetime = field(default_factory=_utc_now)


@dataclass(frozen=True, slots=True)
class EmergencyKillResult:
    """Outcome of emergency kill switch invocation destroying the pending action payload."""

    intent_id: str
    killed: bool
    reason: str
    timestamp: datetime = field(default_factory=_utc_now)
