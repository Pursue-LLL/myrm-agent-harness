"""
[POS] src/myrm_agent_harness/core/security/ephemeral_identity_voucher/ephemeral_identity_broker.py
[INPUT] time, secrets, uuid, types
[OUTPUT] DynamicEphemeralIdentityBroker

Core engine for dynamically issuing, verifying, and terminating short-lived credentials.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import secrets
import time
import uuid

from .types import (
    EphemeralIdentity,
    EphemeralIdentityMetrics,
    IdentityStatus,
)


class DynamicEphemeralIdentityBroker:
    """Provisions micro-scoped ephemeral credentials with strict TTL-based auto-destruction."""

    DEFAULT_TTL_SECONDS: float = 600.0  # 10 minutes maximum lifespan
    MAX_ALLOWED_TTL_SECONDS: float = 3600.0  # 1 hour absolute ceiling

    def __init__(self, metrics: EphemeralIdentityMetrics | None = None) -> None:
        self._identities: dict[str, EphemeralIdentity] = {}
        self._metrics: EphemeralIdentityMetrics = (
            metrics if metrics is not None else EphemeralIdentityMetrics()
        )

    @property
    def metrics(self) -> EphemeralIdentityMetrics:
        """Operational metrics reference."""
        return self._metrics

    def issue_identity(
        self,
        agent_id: str,
        task_id: str,
        allowed_scopes: tuple[str, ...],
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        metadata: dict[str, str] | None = None,
    ) -> EphemeralIdentity:
        """Issue a fresh, cryptographically isolated ephemeral identity.

        Args:
            agent_id: Unique identifier of requesting agent.
            task_id: Active task context.
            allowed_scopes: Explicit capability scopes granted.
            ttl_seconds: Desired lifespan in seconds (capped at MAX_ALLOWED_TTL_SECONDS).
            metadata: Additional non-sensitive diagnostic tags.

        Returns:
            EphemeralIdentity with active status and cryptographically secure token.
        """
        now = time.time()
        effective_ttl = min(max(1.0, ttl_seconds), self.MAX_ALLOWED_TTL_SECONDS)
        expires_at = now + effective_ttl

        identity_id = f"eph-id-{uuid.uuid4().hex[:12]}"
        token = secrets.token_urlsafe(32)

        identity = EphemeralIdentity(
            identity_id=identity_id,
            agent_id=agent_id,
            task_id=task_id,
            allowed_scopes=allowed_scopes,
            ephemeral_token=token,
            created_at_epoch=now,
            expires_at_epoch=expires_at,
            status=IdentityStatus.ACTIVE,
            metadata=dict(metadata) if metadata else {},
        )
        self._identities[identity_id] = identity
        self._metrics.identities_issued_total += 1
        return identity

    def verify_identity(
        self,
        identity_id: str,
        token: str,
        required_scope: str | None = None,
    ) -> tuple[bool, IdentityStatus, str]:
        """Verify credential validity, scope authorization, and expiration.

        Returns:
            Tuple of (is_valid, current_status, diagnostic_reason).
        """
        identity = self._identities.get(identity_id)
        if identity is None:
            return False, IdentityStatus.REVOKED, f"Identity {identity_id} not found"

        now = time.time()

        # Check expiration
        if identity.status == IdentityStatus.ACTIVE and now >= identity.expires_at_epoch:
            expired_identity = EphemeralIdentity(
                identity_id=identity.identity_id,
                agent_id=identity.agent_id,
                task_id=identity.task_id,
                allowed_scopes=identity.allowed_scopes,
                ephemeral_token=identity.ephemeral_token,
                created_at_epoch=identity.created_at_epoch,
                expires_at_epoch=identity.expires_at_epoch,
                status=IdentityStatus.EXPIRED,
                metadata=identity.metadata,
            )
            self._identities[identity_id] = expired_identity
            self._metrics.identities_expired_total += 1
            return False, IdentityStatus.EXPIRED, "Identity TTL expired"

        if identity.status != IdentityStatus.ACTIVE:
            return (
                False,
                identity.status,
                f"Identity is inactive: {identity.status.value}",
            )

        # Constant-time comparison to prevent timing attacks
        if not secrets.compare_digest(identity.ephemeral_token, token):
            return False, IdentityStatus.ACTIVE, "Invalid ephemeral token mismatch"

        # Check scope if requested
        if required_scope is not None and required_scope not in identity.allowed_scopes:
            return (
                False,
                IdentityStatus.ACTIVE,
                f"Required scope '{required_scope}' not authorized in scopes {identity.allowed_scopes}",
            )

        return True, IdentityStatus.ACTIVE, "Identity is valid and active"

    def revoke_identity(
        self, identity_id: str, reason: str = "Explicit revocation"
    ) -> bool:
        """Explicitly revoke an active identity immediately."""
        identity = self._identities.get(identity_id)
        if identity is None or identity.status == IdentityStatus.REVOKED:
            return False

        updated_metadata = dict(identity.metadata)
        updated_metadata["revocation_reason"] = reason

        revoked = EphemeralIdentity(
            identity_id=identity.identity_id,
            agent_id=identity.agent_id,
            task_id=identity.task_id,
            allowed_scopes=identity.allowed_scopes,
            ephemeral_token=identity.ephemeral_token,
            created_at_epoch=identity.created_at_epoch,
            expires_at_epoch=identity.expires_at_epoch,
            status=IdentityStatus.REVOKED,
            metadata=updated_metadata,
        )
        self._identities[identity_id] = revoked
        self._metrics.identities_revoked_total += 1
        return True

    def consume_identity(self, identity_id: str) -> bool:
        """Mark an ephemeral identity as consumed (single-use destruction)."""
        identity = self._identities.get(identity_id)
        if identity is None or identity.status != IdentityStatus.ACTIVE:
            return False

        consumed = EphemeralIdentity(
            identity_id=identity.identity_id,
            agent_id=identity.agent_id,
            task_id=identity.task_id,
            allowed_scopes=identity.allowed_scopes,
            ephemeral_token=identity.ephemeral_token,
            created_at_epoch=identity.created_at_epoch,
            expires_at_epoch=identity.expires_at_epoch,
            status=IdentityStatus.CONSUMED,
            metadata=identity.metadata,
        )
        self._identities[identity_id] = consumed
        return True

    def get_identity(self, identity_id: str) -> EphemeralIdentity | None:
        """Retrieve stored identity snapshot if present."""
        return self._identities.get(identity_id)

    def sweep_expired(self) -> int:
        """Sweep and transition all expired active tokens, returning count."""
        now = time.time()
        swept_count = 0
        for identity_id, identity in list(self._identities.items()):
            if (
                identity.status == IdentityStatus.ACTIVE
                and now >= identity.expires_at_epoch
            ):
                self._identities[identity_id] = EphemeralIdentity(
                    identity_id=identity.identity_id,
                    agent_id=identity.agent_id,
                    task_id=identity.task_id,
                    allowed_scopes=identity.allowed_scopes,
                    ephemeral_token=identity.ephemeral_token,
                    created_at_epoch=identity.created_at_epoch,
                    expires_at_epoch=identity.expires_at_epoch,
                    status=IdentityStatus.EXPIRED,
                    metadata=identity.metadata,
                )
                self._metrics.identities_expired_total += 1
                swept_count += 1
        return swept_count
