"""
[POS] src/myrm_agent_harness/core/security/media_artifact_grants/facade.py
[INPUT] types, grant_gate
[OUTPUT] MediaArtifactRoleScopedGrantsFacade

Unified facade for evaluating, querying, and revoking role-scoped artifact grants.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from .grant_gate import MediaArtifactGrantGate
from .types import (
    GrantEvaluationResult,
    MediaArtifactGrant,
    MediaArtifactGrantMetrics,
    ProducerRole,
)


class MediaArtifactRoleScopedGrantsFacade:
    """Unified entrypoint for the Media Artifact Role-Scoped Grants security suite."""

    def __init__(self) -> None:
        self._metrics = MediaArtifactGrantMetrics()
        self._gate = MediaArtifactGrantGate(metrics=self._metrics)

    @property
    def metrics(self) -> MediaArtifactGrantMetrics:
        """Shared operational metrics."""
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
        """Evaluate artifact inline presentation eligibility based on producer role."""
        return self._gate.evaluate_and_grant(
            session_id=session_id,
            artifact_id=artifact_id,
            producer_role=producer_role,
            mime_type=mime_type,
            checksum_sha256=checksum_sha256,
            metadata=metadata,
        )

    def revoke_grant(
        self, session_id: str, artifact_id: str, reason: str = "Explicit revocation"
    ) -> bool:
        """Revoke an existing artifact inline display grant."""
        return self._gate.revoke_grant(
            session_id=session_id, artifact_id=artifact_id, reason=reason
        )

    def get_grant(
        self, session_id: str, artifact_id: str
    ) -> MediaArtifactGrant | None:
        """Lookup stored grant for artifact in session."""
        return self._gate.get_grant(session_id=session_id, artifact_id=artifact_id)

    def list_grants_for_session(
        self, session_id: str
    ) -> tuple[MediaArtifactGrant, ...]:
        """List all artifact grants registered in session."""
        return self._gate.list_grants_for_session(session_id=session_id)
