"""End-to-end suite orchestrating spawn name reservation until durable admission.

[INPUT]
- agent.context_management.spawn_reservation.reservation_types::AdmissionCommitResult, ReservationResult,
  SpawnReservationLease (POS: Strongly typed contracts for spawn name reservation and admission durability.)
- agent.context_management.spawn_reservation.spawn_name_reservation_engine::SpawnNameReservationEngine (POS:
  Concurrent thread-safe engine managing spawn name reservations until durable admission.)

[OUTPUT]
- SpawnNameReservationUntilAdmissionDurableSuite: Industrial-grade suite guaranteeing spawn names are reserved
  until durable admission.

[POS]
End-to-end suite orchestrating spawn name reservation until durable admission.
"""

from __future__ import annotations

from typing import Callable

from .reservation_types import AdmissionCommitResult, ReservationResult, SpawnReservationLease
from .spawn_name_reservation_engine import SpawnNameReservationEngine


class SpawnNameReservationUntilAdmissionDurableSuite:
    """Industrial-grade suite guaranteeing spawn names are reserved until durable admission."""

    def __init__(self, engine: SpawnNameReservationEngine | None = None) -> None:
        """Initialize the spawn admission suite."""
        self._engine: SpawnNameReservationEngine = engine or SpawnNameReservationEngine()

    @property
    def engine(self) -> SpawnNameReservationEngine:
        """Access underlying reservation engine."""
        return self._engine

    def execute_durable_spawn(
        self,
        parent_session_id: str,
        spawn_name: str,
        durable_writer: Callable[[], str],
        ttl_ms: int = 30_000,
        reservation_token: str | None = None,
        current_time_ms: int | None = None,
    ) -> AdmissionCommitResult:
        """Execute two-phase durable spawn workflow with automatic rollback on storage failure.

        Phase 1: Reserve spawn name under parent session.
        Phase 2: Perform storage write via durable_writer callback.
        Phase 3: Commit reservation to durable state or release upon exception.
        """
        res: ReservationResult = self._engine.reserve_name(
            parent_session_id=parent_session_id,
            spawn_name=spawn_name,
            ttl_ms=ttl_ms,
            reservation_token=reservation_token,
            current_time_ms=current_time_ms,
        )

        if not res.success or res.lease is None:
            return AdmissionCommitResult(
                success=False,
                error_detail=res.rejection_reason or "Spawn name reservation rejected.",
            )

        lease: SpawnReservationLease = res.lease

        try:
            # Perform actual disk/database durable commit
            durable_id = durable_writer()
        except Exception as exc:
            # Storage failure: roll back reservation so name is not orphaned
            self._engine.release_reservation(lease.reservation_id, lease.reservation_token)
            return AdmissionCommitResult(
                success=False,
                error_detail=f"Durable storage persistence failed: {exc}; reservation safely rolled back.",
            )

        # Storage succeeded: promote reservation to committed durable
        commit_res = self._engine.commit_admission(
            reservation_id=lease.reservation_id,
            reservation_token=lease.reservation_token,
            durable_id=durable_id,
            current_time_ms=current_time_ms,
        )

        if not commit_res.success:
            # In the rare event commit failed (e.g., TTL expired during long durable write)
            self._engine.release_reservation(lease.reservation_id, lease.reservation_token)

        return commit_res
