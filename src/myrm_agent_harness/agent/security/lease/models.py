"""Data models for in-flight task lease governor and cascade revocation suite.

[POS]
Immutable contracts defining micro-lease tickets, revocation events,
and structured termination errors for execution-time privilege revocation.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class RevocationSubjectType(StrEnum):
    """Classification of the security subject being revoked."""

    CREDENTIAL = "credential"
    AGENT = "agent"
    RESOURCE = "resource"
    SESSION = "session"


class RevocationTerminatedError(Exception):
    """Raised when an in-flight task is forcefully terminated due to privilege revocation."""

    def __init__(
        self,
        task_id: str,
        subject_id: str,
        subject_type: RevocationSubjectType,
        reason: str,
    ) -> None:
        message = (
            f"In-flight task '{task_id}' was immediately terminated by security revocation: "
            f"Subject [{subject_type.value}:{subject_id}] was revoked (Reason: {reason})"
        )
        super().__init__(message)
        self.task_id = task_id
        self.subject_id = subject_id
        self.subject_type = subject_type
        self.reason = reason


@dataclass(frozen=True, slots=True)
class RevocationEvent:
    """Immutable event describing a real-time security privilege revocation."""

    subject_type: RevocationSubjectType
    subject_id: str
    reason: str
    revoked_at: float = field(default_factory=time.time)
    grace_period_ms: int = 0  # 0 ms for immediate hard termination


@dataclass(frozen=True, slots=True)
class LeaseTicket:
    """Immutable micro-lease ticket held by an in-flight running task."""

    ticket_id: str
    task_id: str
    bound_resources: frozenset[str]
    expires_at: float
    ttl_seconds: float = 30.0

    @property
    def is_expired(self) -> bool:
        """Check whether the lease ticket has expired past its validity window."""
        return time.time() > self.expires_at

    def renew(self, ttl_seconds: float = 30.0) -> LeaseTicket:
        """Create a renewed lease ticket with extended expiry time."""
        return LeaseTicket(
            ticket_id=self.ticket_id,
            task_id=self.task_id,
            bound_resources=self.bound_resources,
            expires_at=time.time() + ttl_seconds,
            ttl_seconds=ttl_seconds,
        )
