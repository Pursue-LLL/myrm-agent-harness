# [INPUT]: None
# [OUTPUT]: ReservationState, SpawnReservationLease, ReservationResult, AdmissionCommitResult
# [POS]: agent/context_management/spawn_reservation/reservation_types.py

"""Strongly typed contracts for spawn name reservation and admission durability.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- ReservationState: Lifecycle state of a spawn name reservation.
- SpawnReservationLease: An atomic reservation lease holding a spawn name until admission is durable.
- ReservationResult: Outcome of attempting to reserve a spawn name.
- AdmissionCommitResult: Outcome of committing a reserved spawn name to durable admission.

[POS]
Strongly typed contracts for spawn name reservation and admission durability.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ReservationState(str, Enum):
    """Lifecycle state of a spawn name reservation."""

    PENDING_ADMISSION = "pending_admission"
    COMMITTED_DURABLE = "committed_durable"
    EXPIRED = "expired"
    RELEASED = "released"


@dataclass(frozen=True)
class SpawnReservationLease:
    """An atomic reservation lease holding a spawn name until admission is durable."""

    reservation_id: str
    parent_session_id: str
    spawn_name: str
    state: ReservationState
    created_at_epoch_ms: int
    expires_at_epoch_ms: int
    reservation_token: str
    durable_id: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)

    def is_expired(self, current_time_ms: int) -> bool:
        """Check if lease has expired at specified timestamp."""
        return self.state == ReservationState.PENDING_ADMISSION and current_time_ms >= self.expires_at_epoch_ms


@dataclass(frozen=True)
class ReservationResult:
    """Outcome of attempting to reserve a spawn name."""

    success: bool
    lease: SpawnReservationLease | None
    rejection_reason: str | None = None
    is_idempotent_replay: bool = False


@dataclass(frozen=True)
class AdmissionCommitResult:
    """Outcome of committing a reserved spawn name to durable admission."""

    success: bool
    durable_id: str | None = None
    committed_at_epoch_ms: int | None = None
    error_detail: str | None = None
