"""One-Shot Atomic Operation Grant Manager with parameter hash binding and change invalidation.

[INPUT]
- operation_name, canonical payload dictionary or hash, grant_id

[OUTPUT]
- AtomicOperationGrant tracking one-shot lifecycle: PENDING -> GRANTED -> USED
- AtomicGrantInvalidatedError on tampering, expiry, reuse, or terminal revocation.

[POS]
- Harness core security module inspired by OpenClaw 2.0 (one-shot operation grants).
- Guarantees sensitive operations (payments, mutations, emails) are authorized for exact payloads once.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections.abc import Mapping

from myrm_agent_harness.core.security.secret_broker.types import (
    AtomicGrantInvalidatedError,
    AtomicOperationGrant,
    GrantStatus,
)


class AtomicOperationGrantManager:
    """Thread-safe manager for one-shot operation grants with payload hash integrity."""

    def __init__(self) -> None:
        self._grants: dict[str, AtomicOperationGrant] = {}
        self._rejection_reasons: dict[str, str] = {}
        self._lock = threading.Lock()

    @staticmethod
    def compute_payload_hash(payload: Mapping[str, object]) -> str:
        """Compute deterministic SHA-256 hash of a payload dictionary."""
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def create_grant(
        self,
        operation_name: str,
        payload_hash: str,
        ttl_seconds: float = 180.0,
    ) -> AtomicOperationGrant:
        """Create a new pending one-shot operation grant bound to an exact payload hash."""
        grant_id = f"grnt_{hashlib.sha256(f'{operation_name}:{payload_hash}:{time.time()}'.encode()).hexdigest()[:12]}"
        now = time.time()
        grant = AtomicOperationGrant(
            grant_id=grant_id,
            operation_name=operation_name,
            payload_hash=payload_hash,
            status=GrantStatus.PENDING,
            created_at=now,
            expires_at=now + ttl_seconds,
        )
        with self._lock:
            self._grants[grant_id] = grant
        return grant

    def approve_grant(self, grant_id: str) -> AtomicOperationGrant:
        """Transition pending grant to GRANTED status."""
        with self._lock:
            grant = self._grants.get(grant_id)
            if not grant:
                raise KeyError(f"Grant '{grant_id}' not found")
            if grant.status != GrantStatus.PENDING:
                raise AtomicGrantInvalidatedError(
                    grant_id, f"Cannot approve grant in status '{grant.status.value}'"
                )
            if time.time() > grant.expires_at:
                updated = AtomicOperationGrant(
                    grant_id=grant.grant_id,
                    operation_name=grant.operation_name,
                    payload_hash=grant.payload_hash,
                    status=GrantStatus.INVALIDATED,
                    created_at=grant.created_at,
                    expires_at=grant.expires_at,
                )
                self._grants[grant_id] = updated
                raise AtomicGrantInvalidatedError(grant_id, "Grant expired before approval")

            updated = AtomicOperationGrant(
                grant_id=grant.grant_id,
                operation_name=grant.operation_name,
                payload_hash=grant.payload_hash,
                status=GrantStatus.GRANTED,
                created_at=grant.created_at,
                expires_at=grant.expires_at,
            )
            self._grants[grant_id] = updated
            return updated

    def reject_grant(self, grant_id: str, reason: str = "User denied") -> AtomicOperationGrant:
        """Terminally revoke a grant. Agent is forbidden from retrying or re-requesting."""
        with self._lock:
            grant = self._grants.get(grant_id)
            if not grant:
                raise KeyError(f"Grant '{grant_id}' not found")

            updated = AtomicOperationGrant(
                grant_id=grant.grant_id,
                operation_name=grant.operation_name,
                payload_hash=grant.payload_hash,
                status=GrantStatus.REVOKED,
                created_at=grant.created_at,
                expires_at=grant.expires_at,
            )
            self._grants[grant_id] = updated
            self._rejection_reasons[grant_id] = reason
            return updated

    def consume_grant(
        self,
        grant_id: str,
        operation_name: str,
        current_payload_hash: str,
    ) -> bool:
        """Verify and consume a grant once. Invalidate immediately upon parameter deviation."""
        with self._lock:
            grant = self._grants.get(grant_id)
            if not grant:
                raise KeyError(f"Grant '{grant_id}' not found")

            if grant.status == GrantStatus.REVOKED:
                reason = self._rejection_reasons.get(grant_id, "Operation was explicitly denied")
                raise AtomicGrantInvalidatedError(
                    grant_id, f"Grant is terminally revoked and closed: {reason}"
                )

            if grant.status == GrantStatus.USED:
                raise AtomicGrantInvalidatedError(
                    grant_id, "Grant has already been consumed (single-use enforced)"
                )

            if grant.status != GrantStatus.GRANTED:
                raise AtomicGrantInvalidatedError(
                    grant_id, f"Grant is not in granted status (current: {grant.status.value})"
                )

            if time.time() > grant.expires_at:
                self._grants[grant_id] = AtomicOperationGrant(
                    grant_id=grant.grant_id,
                    operation_name=grant.operation_name,
                    payload_hash=grant.payload_hash,
                    status=GrantStatus.INVALIDATED,
                    created_at=grant.created_at,
                    expires_at=grant.expires_at,
                )
                raise AtomicGrantInvalidatedError(grant_id, "Grant expired before execution")

            if grant.operation_name != operation_name:
                self._grants[grant_id] = AtomicOperationGrant(
                    grant_id=grant.grant_id,
                    operation_name=grant.operation_name,
                    payload_hash=grant.payload_hash,
                    status=GrantStatus.INVALIDATED,
                    created_at=grant.created_at,
                    expires_at=grant.expires_at,
                )
                raise AtomicGrantInvalidatedError(
                    grant_id,
                    f"Operation name mismatch: expected '{grant.operation_name}', got '{operation_name}'",
                )

            # Invalidate immediately if payload hash was mutated
            if grant.payload_hash != current_payload_hash:
                self._grants[grant_id] = AtomicOperationGrant(
                    grant_id=grant.grant_id,
                    operation_name=grant.operation_name,
                    payload_hash=grant.payload_hash,
                    status=GrantStatus.INVALIDATED,
                    created_at=grant.created_at,
                    expires_at=grant.expires_at,
                )
                raise AtomicGrantInvalidatedError(
                    grant_id,
                    "Payload mutation detected after approval! Atomic grant invalidated immediately.",
                )

            # Mark as USED
            self._grants[grant_id] = AtomicOperationGrant(
                grant_id=grant.grant_id,
                operation_name=grant.operation_name,
                payload_hash=grant.payload_hash,
                status=GrantStatus.USED,
                created_at=grant.created_at,
                expires_at=grant.expires_at,
            )
            return True

    def get_grant(self, grant_id: str) -> AtomicOperationGrant | None:
        """Retrieve grant by ID."""
        with self._lock:
            return self._grants.get(grant_id)

    def list_grants(self) -> list[AtomicOperationGrant]:
        """List all active or historical grants."""
        with self._lock:
            return list(self._grants.values())
