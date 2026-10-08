"""Concurrent thread-safe engine managing spawn name reservations until durable admission.

[INPUT]
- agent.context_management.spawn_reservation.reservation_types::AdmissionCommitResult, ReservationResult,
  ReservationState, SpawnReservationLease (POS: Strongly typed contracts for spawn name reservation and
  admission durability.)

[OUTPUT]
- SpawnNameReservationEngine: Thread-safe engine ensuring no two concurrent spawns claim the same name.

[POS]
Concurrent thread-safe engine managing spawn name reservations until durable admission.
"""

from __future__ import annotations

import threading
import time
import uuid

from .reservation_types import (
    AdmissionCommitResult,
    ReservationResult,
    ReservationState,
    SpawnReservationLease,
)


class SpawnNameReservationEngine:
    """Thread-safe engine ensuring no two concurrent spawns claim the same name."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # Key: (parent_session_id, normalized_spawn_name) -> SpawnReservationLease
        self._active_leases: dict[tuple[str, str], SpawnReservationLease] = {}
        # Key: reservation_id -> (parent_session_id, normalized_spawn_name)
        self._id_index: dict[str, tuple[str, str]] = {}

    def reserve_name(
        self,
        parent_session_id: str,
        spawn_name: str,
        ttl_ms: int = 30_000,
        reservation_token: str | None = None,
        current_time_ms: int | None = None,
    ) -> ReservationResult:
        """Atomically reserve a spawn name under a parent session."""
        normalized_name = spawn_name.strip().lower()
        if not normalized_name:
            return ReservationResult(
                success=False,
                lease=None,
                rejection_reason="Spawn name cannot be empty or blank.",
            )

        now_ms = current_time_ms if current_time_ms is not None else int(time.time() * 1000)
        token = reservation_token or str(uuid.uuid4())
        lookup_key = (parent_session_id, normalized_name)

        with self._lock:
            existing = self._active_leases.get(lookup_key)
            if existing is not None:
                # Case 1: Already durable
                if existing.state == ReservationState.COMMITTED_DURABLE:
                    return ReservationResult(
                        success=False,
                        lease=None,
                        rejection_reason=f"Spawn name '{spawn_name}' is already durable under session '{parent_session_id}'.",
                    )

                # Case 2: Pending admission
                if existing.state == ReservationState.PENDING_ADMISSION:
                    if existing.is_expired(now_ms):
                        # Expired lease, evict and proceed
                        self._evict_lease_unsafe(existing)
                    elif existing.reservation_token == token:
                        # Idempotent retry by the same caller
                        return ReservationResult(
                            success=True,
                            lease=existing,
                            is_idempotent_replay=True,
                        )
                    else:
                        # Concurrent reservation clash
                        return ReservationResult(
                            success=False,
                            lease=None,
                            rejection_reason=(
                                f"Spawn name '{spawn_name}' is currently held by active reservation "
                                f"'{existing.reservation_id}' until {existing.expires_at_epoch_ms}."
                            ),
                        )

            # Create new pending reservation lease
            res_id = f"res_{uuid.uuid4().hex[:12]}"
            new_lease = SpawnReservationLease(
                reservation_id=res_id,
                parent_session_id=parent_session_id,
                spawn_name=spawn_name,
                state=ReservationState.PENDING_ADMISSION,
                created_at_epoch_ms=now_ms,
                expires_at_epoch_ms=now_ms + ttl_ms,
                reservation_token=token,
            )
            self._active_leases[lookup_key] = new_lease
            self._id_index[res_id] = lookup_key

            return ReservationResult(success=True, lease=new_lease)

    def commit_admission(
        self,
        reservation_id: str,
        reservation_token: str,
        durable_id: str,
        current_time_ms: int | None = None,
    ) -> AdmissionCommitResult:
        """Atomically transition a pending reservation into committed durable status."""
        now_ms = current_time_ms if current_time_ms is not None else int(time.time() * 1000)

        with self._lock:
            lookup_key = self._id_index.get(reservation_id)
            if lookup_key is None:
                return AdmissionCommitResult(
                    success=False,
                    error_detail=f"Reservation id '{reservation_id}' not found.",
                )

            lease = self._active_leases.get(lookup_key)
            if lease is None or lease.reservation_id != reservation_id:
                return AdmissionCommitResult(
                    success=False,
                    error_detail=f"Reservation lease discrepancy for id '{reservation_id}'.",
                )

            if lease.reservation_token != reservation_token:
                return AdmissionCommitResult(
                    success=False,
                    error_detail="Reservation token mismatch: unauthorized admission attempt.",
                )

            if lease.state == ReservationState.COMMITTED_DURABLE:
                # Already committed idempotently
                return AdmissionCommitResult(
                    success=True,
                    durable_id=lease.durable_id,
                    committed_at_epoch_ms=lease.created_at_epoch_ms,
                )

            if lease.is_expired(now_ms):
                self._evict_lease_unsafe(lease)
                return AdmissionCommitResult(
                    success=False,
                    error_detail=f"Reservation '{reservation_id}' expired before admission became durable.",
                )

            # Commit to durable
            durable_lease = SpawnReservationLease(
                reservation_id=lease.reservation_id,
                parent_session_id=lease.parent_session_id,
                spawn_name=lease.spawn_name,
                state=ReservationState.COMMITTED_DURABLE,
                created_at_epoch_ms=lease.created_at_epoch_ms,
                expires_at_epoch_ms=lease.expires_at_epoch_ms,
                reservation_token=lease.reservation_token,
                durable_id=durable_id,
                metadata=dict(lease.metadata),
            )
            self._active_leases[lookup_key] = durable_lease

            return AdmissionCommitResult(
                success=True,
                durable_id=durable_id,
                committed_at_epoch_ms=now_ms,
            )

    def release_reservation(self, reservation_id: str, reservation_token: str) -> bool:
        """Release a pending reservation upon failure or explicit cancellation."""
        with self._lock:
            lookup_key = self._id_index.get(reservation_id)
            if lookup_key is None:
                return False

            lease = self._active_leases.get(lookup_key)
            if lease is None or lease.reservation_token != reservation_token:
                return False

            if lease.state == ReservationState.COMMITTED_DURABLE:
                # Committed durable names cannot be released via reservation token
                return False

            self._evict_lease_unsafe(lease)
            return True

    def get_lease(self, parent_session_id: str, spawn_name: str) -> SpawnReservationLease | None:
        """Get the current lease for a spawn name if any."""
        normalized_name = spawn_name.strip().lower()
        with self._lock:
            return self._active_leases.get((parent_session_id, normalized_name))

    def clean_expired_leases(self, current_time_ms: int | None = None) -> int:
        """Clean up all expired pending leases and return count of evicted leases."""
        now_ms = current_time_ms if current_time_ms is not None else int(time.time() * 1000)
        evicted_count = 0

        with self._lock:
            keys_to_check = list(self._active_leases.keys())
            for key in keys_to_check:
                lease = self._active_leases[key]
                if lease.state == ReservationState.PENDING_ADMISSION and lease.is_expired(now_ms):
                    self._evict_lease_unsafe(lease)
                    evicted_count += 1

        return evicted_count

    def _evict_lease_unsafe(self, lease: SpawnReservationLease) -> None:
        """Internal helper to evict lease from active indexes without acquiring lock."""
        lookup_key = (lease.parent_session_id, lease.spawn_name.strip().lower())
        self._active_leases.pop(lookup_key, None)
        self._id_index.pop(lease.reservation_id, None)
