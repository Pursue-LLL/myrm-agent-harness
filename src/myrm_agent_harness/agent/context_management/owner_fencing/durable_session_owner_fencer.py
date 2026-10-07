"""Core implementation of Durable Session Owner Fencing and Admission Control Engine.

Provides monotonic epoch leases, admission validation gates, quiesce states,
and double-write prevention fencing across multi-client reconnects.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid

from .owner_fencing_types import (
    AdmissionDecision,
    AdmissionStatus,
    FencingConfig,
    SessionOwnerLease,
    SessionQuiesceState,
)

logger = logging.getLogger(__name__)


class DurableSessionOwnerFencer:
    """Coordinates durable session ownership epochs and turn admission gates."""

    def __init__(self, config: FencingConfig | None = None) -> None:
        self._config = config or FencingConfig()
        self._lock = threading.RLock()
        self._leases: dict[str, SessionOwnerLease] = {}
        self._epochs: dict[str, int] = {}
        self._quiesce_states: dict[str, SessionQuiesceState] = {}

    def acquire_or_takeover_lease(
        self,
        session_id: str,
        client_id: str,
    ) -> SessionOwnerLease:
        """Acquire an active owner lease for a session, monotonically bumping epoch on takeover."""
        with self._lock:
            now = time.time()
            ttl = self._config.lease_ttl_seconds
            current_lease = self._leases.get(session_id)
            current_epoch = self._epochs.get(session_id, 0)

            # 1. First-time session lease acquisition
            if current_lease is None:
                new_epoch = 1
                self._epochs[session_id] = new_epoch
                token = f"lease-ep{new_epoch}-{uuid.uuid4().hex[:8]}"
                lease = SessionOwnerLease(
                    session_id=session_id,
                    client_id=client_id,
                    epoch=new_epoch,
                    lease_token=token,
                    granted_at=now,
                    expires_at=now + ttl,
                )
                self._leases[session_id] = lease
                self._quiesce_states[session_id] = SessionQuiesceState.ACTIVE
                logger.info("Session '%s' lease initialized: client='%s', epoch=%d", session_id, client_id, new_epoch)
                return lease

            # 2. Same client extending/renewing valid lease
            if current_lease.client_id == client_id and now <= current_lease.expires_at:
                renewed = SessionOwnerLease(
                    session_id=session_id,
                    client_id=client_id,
                    epoch=current_lease.epoch,
                    lease_token=current_lease.lease_token,
                    granted_at=current_lease.granted_at,
                    expires_at=now + ttl,
                )
                self._leases[session_id] = renewed
                return renewed

            # 3. Takeover by new client or recovery from expired lease -> bump monotonic epoch
            new_epoch = current_epoch + 1
            self._epochs[session_id] = new_epoch
            token = f"lease-ep{new_epoch}-{uuid.uuid4().hex[:8]}"
            new_lease = SessionOwnerLease(
                session_id=session_id,
                client_id=client_id,
                epoch=new_epoch,
                lease_token=token,
                granted_at=now,
                expires_at=now + ttl,
            )
            self._leases[session_id] = new_lease
            self._quiesce_states[session_id] = SessionQuiesceState.ACTIVE
            logger.warning(
                "Session '%s' lease takeover: new_client='%s', old_client='%s', bumped epoch %d -> %d",
                session_id,
                client_id,
                current_lease.client_id,
                current_epoch,
                new_epoch,
            )
            return new_lease

    def admit_turn(
        self,
        session_id: str,
        client_id: str,
        lease_token: str,
        requested_epoch: int | None = None,
    ) -> AdmissionDecision:
        """Evaluate if an incoming turn or event injection is authorized under current epoch fence."""
        with self._lock:
            now = time.time()
            current_epoch = self._epochs.get(session_id, 0)

            # 1. Quiesce check
            quiesce = self._quiesce_states.get(session_id, SessionQuiesceState.IDLE)
            if quiesce == SessionQuiesceState.QUIESCING:
                return AdmissionDecision(
                    status=AdmissionStatus.STORAGE_BUSY,
                    allowed=False,
                    current_epoch=current_epoch,
                    requested_epoch=requested_epoch,
                    client_id=client_id,
                    reason="Session is quiescing for reset or maintenance; storage busy.",
                )

            # 2. Active lease check
            active_lease = self._leases.get(session_id)
            if active_lease is None:
                return AdmissionDecision(
                    status=AdmissionStatus.INVALID_LEASE,
                    allowed=False,
                    current_epoch=current_epoch,
                    requested_epoch=requested_epoch,
                    client_id=client_id,
                    reason="No active owner lease exists for this session.",
                )

            # 3. Token and client matching
            if active_lease.lease_token != lease_token or active_lease.client_id != client_id:
                return AdmissionDecision(
                    status=AdmissionStatus.FENCED_REJECTED,
                    allowed=False,
                    current_epoch=active_lease.epoch,
                    requested_epoch=requested_epoch,
                    client_id=client_id,
                    reason=f"Client '{client_id}' is fenced; current lease held by '{active_lease.client_id}'.",
                )

            # 4. TTL expiration check
            if now > active_lease.expires_at:
                return AdmissionDecision(
                    status=AdmissionStatus.INVALID_LEASE,
                    allowed=False,
                    current_epoch=active_lease.epoch,
                    requested_epoch=requested_epoch,
                    client_id=client_id,
                    reason="Active owner lease has expired.",
                )

            # 5. Stale epoch check if explicit epoch provided
            if requested_epoch is not None and requested_epoch < active_lease.epoch:
                return AdmissionDecision(
                    status=AdmissionStatus.FENCED_REJECTED,
                    allowed=False,
                    current_epoch=active_lease.epoch,
                    requested_epoch=requested_epoch,
                    client_id=client_id,
                    reason=f"Stale epoch {requested_epoch}; active epoch is {active_lease.epoch}.",
                )

            # Admitted
            return AdmissionDecision(
                status=AdmissionStatus.ADMITTED,
                allowed=True,
                current_epoch=active_lease.epoch,
                requested_epoch=requested_epoch or active_lease.epoch,
                client_id=client_id,
                reason="Admitted under active owner lease fence.",
            )

    def quiesce_session(self, session_id: str) -> None:
        """Place session into quiescing state, temporarily rejecting turn admissions with STORAGE_BUSY."""
        with self._lock:
            self._quiesce_states[session_id] = SessionQuiesceState.QUIESCING
            logger.info("Session '%s' transitioned to QUIESCING", session_id)

    def resume_session(self, session_id: str) -> None:
        """Resume session to ACTIVE state from quiescence."""
        with self._lock:
            self._quiesce_states[session_id] = SessionQuiesceState.ACTIVE
            logger.info("Session '%s' resumed to ACTIVE", session_id)

    def release_lease(self, session_id: str, client_id: str, lease_token: str) -> bool:
        """Explicitly release active lease if held by caller."""
        with self._lock:
            current = self._leases.get(session_id)
            if current and current.client_id == client_id and current.lease_token == lease_token:
                del self._leases[session_id]
                self._quiesce_states[session_id] = SessionQuiesceState.IDLE
                logger.info("Session '%s' lease released by client '%s'", session_id, client_id)
                return True
            return False

    def get_active_lease(self, session_id: str) -> SessionOwnerLease | None:
        """Query currently active lease for session."""
        with self._lock:
            return self._leases.get(session_id)

    def get_current_epoch(self, session_id: str) -> int:
        """Query current epoch counter for session."""
        with self._lock:
            return self._epochs.get(session_id, 0)
