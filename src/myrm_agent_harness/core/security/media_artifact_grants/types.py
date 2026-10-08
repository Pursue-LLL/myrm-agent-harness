"""
[POS] src/myrm_agent_harness/core/security/media_artifact_grants/types.py
[INPUT] dataclasses, enum, typing
[OUTPUT] ProducerRole, ArtifactGrantStatus, MediaArtifactGrant, GrantEvaluationResult, MediaArtifactGrantMetrics

Domain types for Media Artifact Role-Scoped Grants Suite.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ProducerRole(StrEnum):
    """Originator role producing the artifact/media within the session."""

    ASSISTANT = "ASSISTANT"
    TOOL = "TOOL"
    USER = "USER"
    EXTERNAL_UNTRUSTED = "EXTERNAL_UNTRUSTED"


class ArtifactGrantStatus(StrEnum):
    """Authorization status governing inline presentation of the artifact."""

    INLINE_RENDER_GRANTED = "INLINE_RENDER_GRANTED"
    UNAUTHORIZED_EXTERNAL = "UNAUTHORIZED_EXTERNAL"
    REVOKED = "REVOKED"
    FALLBACK_DOWNLOAD_ONLY = "FALLBACK_DOWNLOAD_ONLY"


@dataclass(frozen=True)
class MediaArtifactGrant:
    """Security grant record linking session artifact to its verified producer role."""

    artifact_id: str
    session_id: str
    producer_role: ProducerRole
    mime_type: str
    is_inline_allowed: bool
    grant_status: ArtifactGrantStatus
    granted_at_epoch: float
    checksum_sha256: str
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class GrantEvaluationResult:
    """Outcome of evaluating an artifact inline rendering request."""

    is_allowed: bool
    grant_status: ArtifactGrantStatus
    rendered_preview_mode: str
    diagnostic_reason: str
    artifact_id: str
    session_id: str


@dataclass
class MediaArtifactGrantMetrics:
    """Cumulative operational metrics for role-scoped artifact security gates."""

    grants_evaluated_total: int = 0
    inline_granted_total: int = 0
    external_blocked_total: int = 0
    grants_revoked_total: int = 0
