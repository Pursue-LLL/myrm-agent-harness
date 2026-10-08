"""
[POS] src/myrm_agent_harness/core/security/media_artifact_grants/grant_gate.py
[INPUT] time, types
[OUTPUT] MediaArtifactGrantGate

Enforces role-scoped inline presentation grants for media and artifacts within sessions.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import time

from .types import (
    ArtifactGrantStatus,
    GrantEvaluationResult,
    MediaArtifactGrant,
    MediaArtifactGrantMetrics,
    ProducerRole,
)


class MediaArtifactGrantGate:
    """Security gate restricting inline media/artifact rendering strictly to assistant and tool roles."""

    TRUSTED_ROLES: tuple[ProducerRole, ...] = (
        ProducerRole.ASSISTANT,
        ProducerRole.TOOL,
    )

    def __init__(self, metrics: MediaArtifactGrantMetrics | None = None) -> None:
        # (session_id, artifact_id) -> MediaArtifactGrant
        self._grants: dict[tuple[str, str], MediaArtifactGrant] = {}
        self._metrics = metrics if metrics is not None else MediaArtifactGrantMetrics()

    @property
    def metrics(self) -> MediaArtifactGrantMetrics:
        """Operational metrics reference."""
        return self._metrics

    def evaluate_and_grant(
        self,
        session_id: str,
        artifact_id: str,
        producer_role: ProducerRole,
        mime_type: str,
        checksum_sha256: str = "",
        metadata: dict[str, str] | None = None,
    ) -> GrantEvaluationResult:
        """Evaluate an artifact creation or inline rendering request based on originator role."""
        now = time.time()
        self._metrics.grants_evaluated_total += 1
        key = (session_id, artifact_id)

        # Check existing grant if already evaluated
        existing = self._grants.get(key)
        if existing is not None:
            if existing.grant_status == ArtifactGrantStatus.REVOKED:
                return GrantEvaluationResult(
                    is_allowed=False,
                    grant_status=ArtifactGrantStatus.REVOKED,
                    rendered_preview_mode="SAFE_LINK_ONLY",
                    diagnostic_reason=f"Grant for artifact {artifact_id} was explicitly revoked",
                    artifact_id=artifact_id,
                    session_id=session_id,
                )
            preview_mode = "INLINE" if existing.is_inline_allowed else "SAFE_LINK_ONLY"
            return GrantEvaluationResult(
                is_allowed=existing.is_inline_allowed,
                grant_status=existing.grant_status,
                rendered_preview_mode=preview_mode,
                diagnostic_reason="Returning cached verified role evaluation result",
                artifact_id=artifact_id,
                session_id=session_id,
            )

        # Enforce role-scoped boundary: Only assistant and tool roles receive automatic inline presentation grant
        if producer_role in self.TRUSTED_ROLES:
            grant = MediaArtifactGrant(
                artifact_id=artifact_id,
                session_id=session_id,
                producer_role=producer_role,
                mime_type=mime_type,
                is_inline_allowed=True,
                grant_status=ArtifactGrantStatus.INLINE_RENDER_GRANTED,
                granted_at_epoch=now,
                checksum_sha256=checksum_sha256,
                metadata=dict(metadata) if metadata else {},
            )
            self._grants[key] = grant
            self._metrics.inline_granted_total += 1
            return GrantEvaluationResult(
                is_allowed=True,
                grant_status=ArtifactGrantStatus.INLINE_RENDER_GRANTED,
                rendered_preview_mode="INLINE",
                diagnostic_reason=f"Trusted role '{producer_role.value}' verified: granted inline render privileges",
                artifact_id=artifact_id,
                session_id=session_id,
            )

        # Untrusted / user origin: Deny automatic inline rendering, fallback to download-only safe link
        blocked_grant = MediaArtifactGrant(
            artifact_id=artifact_id,
            session_id=session_id,
            producer_role=producer_role,
            mime_type=mime_type,
            is_inline_allowed=False,
            grant_status=ArtifactGrantStatus.UNAUTHORIZED_EXTERNAL,
            granted_at_epoch=now,
            checksum_sha256=checksum_sha256,
            metadata=dict(metadata) if metadata else {},
        )
        self._grants[key] = blocked_grant
        self._metrics.external_blocked_total += 1
        return GrantEvaluationResult(
            is_allowed=False,
            grant_status=ArtifactGrantStatus.UNAUTHORIZED_EXTERNAL,
            rendered_preview_mode="SAFE_LINK_ONLY",
            diagnostic_reason=(
                f"Originator role '{producer_role.value}' is untrusted for automatic inline display. "
                "Restricted to safe isolated link."
            ),
            artifact_id=artifact_id,
            session_id=session_id,
        )

    def revoke_grant(
        self, session_id: str, artifact_id: str, reason: str = "Explicit revocation"
    ) -> bool:
        """Revoke an existing artifact inline display grant."""
        key = (session_id, artifact_id)
        grant = self._grants.get(key)
        if grant is None or grant.grant_status == ArtifactGrantStatus.REVOKED:
            return False

        meta = dict(grant.metadata)
        meta["revocation_reason"] = reason

        revoked = MediaArtifactGrant(
            artifact_id=grant.artifact_id,
            session_id=grant.session_id,
            producer_role=grant.producer_role,
            mime_type=grant.mime_type,
            is_inline_allowed=False,
            grant_status=ArtifactGrantStatus.REVOKED,
            granted_at_epoch=grant.granted_at_epoch,
            checksum_sha256=grant.checksum_sha256,
            metadata=meta,
        )
        self._grants[key] = revoked
        self._metrics.grants_revoked_total += 1
        return True

    def get_grant(self, session_id: str, artifact_id: str) -> MediaArtifactGrant | None:
        """Lookup stored grant for artifact in session."""
        return self._grants.get((session_id, artifact_id))

    def list_grants_for_session(
        self, session_id: str
    ) -> tuple[MediaArtifactGrant, ...]:
        """List all artifact grants registered under specified session."""
        return tuple(g for (s_id, _), g in self._grants.items() if s_id == session_id)
