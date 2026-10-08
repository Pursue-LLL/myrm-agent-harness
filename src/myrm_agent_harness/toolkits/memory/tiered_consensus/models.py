"""Domain models for Tiered Memory Hierarchy and Proposed Consensus Flow Suite.

P1 delivery for Item 114 in topic_01 memory roadmap.
Enforces physical scoping (Personal vs Project vs Team Consensus) and governance
workflows (Proposed -> Approved -> Rejected -> Revoked) to prevent hallucination leaks.

[INPUT]
- Third-party: pydantic

[OUTPUT]
- ConsensusScopeTier: Semantic boundary tier governing memory lifecycle and visibility.
- ProposalStatus: Lifecycle governance status of a tiered memory record.
- compute_content_fingerprint(): Generate deterministic SHA-256 fingerprint for deduplication.
- TieredMemoryRecord: Scoped memory record governed by consensus lifecycle.
- ConsensusAuditLog: Immutable audit entry capturing lifecycle transition events.

[POS]
Domain models for Tiered Memory Hierarchy and Proposed Consensus Flow Suite.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class ConsensusScopeTier(StrEnum):
    """Semantic boundary tier governing memory lifecycle and visibility."""

    PERSONAL = "personal"                # Private user habits, personal preferences, instant auto-approval
    PROJECT = "project"                  # Workspace or repository specific context, auto-approved for project
    TEAM_CONSENSUS = "team_consensus"    # Universal normative guidelines across team, requires explicit approval


class ProposalStatus(StrEnum):
    """Lifecycle governance status of a tiered memory record."""

    PROPOSED = "proposed"    # Draft proposition awaiting explicit human/owner approval
    APPROVED = "approved"    # Authoritative active memory verified for universal consumption
    REJECTED = "rejected"    # Vetoed or discarded proposition preserved for negative evidence
    REVOKED = "revoked"      # Previously approved guideline safely retired with audit retention


def compute_content_fingerprint(content: str) -> str:
    """Generate deterministic SHA-256 fingerprint for deduplication."""
    normalized = content.strip().lower().encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()[:16]


class TieredMemoryRecord(BaseModel):
    """Scoped memory record governed by consensus lifecycle."""

    record_id: str = Field(description="Unique system identifier for the record")
    scope_tier: ConsensusScopeTier = Field(description="Boundary tier: personal, project, or team_consensus")
    content: str = Field(description="Memory guideline or normative rule statement")
    content_fingerprint: str = Field(description="Deterministic hash for idempotent deduplication")
    owner_peer_id: str = Field(description="Peer ID of originator (human user or proposing agent)")
    project_id: str | None = Field(default=None, description="Associated project identifier for project tier")
    status: ProposalStatus = Field(description="Current lifecycle stage: proposed, approved, rejected, revoked")
    version: int = Field(default=1, ge=1, description="Sequential version counter for supersession tracking")
    superseded_by: str | None = Field(default=None, description="Record ID of newer consensus replacing this one")
    rationale: str = Field(default="", description="Originating context or rationale statement")
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class ConsensusAuditLog(BaseModel):
    """Immutable audit entry capturing lifecycle transition events."""

    audit_id: str = Field(description="Unique identifier for audit log entry")
    record_id: str = Field(description="Target memory record identifier")
    action: str = Field(description="Lifecycle transition verb: propose, approve, reject, revoke")
    operator_peer_id: str = Field(description="Peer ID executing the lifecycle action")
    reason: str = Field(default="", description="Justification or evidence accompanying transition")
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
