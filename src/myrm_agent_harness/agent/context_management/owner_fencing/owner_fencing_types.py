"""Type definitions for Durable Session Owner Fencing and Admission Control Suite.

Provides immutable data contracts for monotonic epoch leases, admission decisions,
quiesce states, and split-brain double-write prevention gates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import time


class AdmissionStatus(StrEnum):
    """Categorical status emitted by the durable session admission gate."""

    ADMITTED = "admitted"
    FENCED_REJECTED = "fenced_rejected"
    STORAGE_BUSY = "storage_busy"
    INVALID_LEASE = "invalid_lease"


class SessionQuiesceState(StrEnum):
    """Lifecycle quiesce state of a durable session."""

    IDLE = "idle"
    QUIESCING = "quiescing"
    ACTIVE = "active"


@dataclass(frozen=True)
class FencingConfig:
    """Configuration governing session owner fencing and lease validation."""

    lease_ttl_seconds: float = 60.0
    auto_bump_epoch_on_takeover: bool = True
    max_quiesce_timeout_seconds: float = 10.0


@dataclass(frozen=True)
class SessionOwnerLease:
    """Represents an active, epoch-stamped lease locking ownership of a durable session."""

    session_id: str
    client_id: str
    epoch: int
    lease_token: str
    granted_at: float = field(default_factory=time.time)
    expires_at: float = field(default_factory=lambda: time.time() + 60.0)


@dataclass(frozen=True)
class AdmissionDecision:
    """Outcome of attempting to admit a turn or action into a durable session."""

    status: AdmissionStatus
    allowed: bool
    current_epoch: int
    requested_epoch: int | None
    client_id: str
    reason: str
    decided_at: float = field(default_factory=time.time)
