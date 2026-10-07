"""[POS]: src/myrm_agent_harness/toolkits/memory/capacity_hitl/models.py
[INPUT]: None.
[OUTPUT]: Strongly-typed schemas for near-capacity alerts, HITL candidate proposals, and resolution actions.
"""

from enum import StrEnum

from pydantic import BaseModel, Field


class CapacityAlertKind(StrEnum):
    """Memory capacity alert status thresholds."""

    NORMAL = "normal"
    NEAR_CAPACITY = "near_capacity"
    CRITICAL_FULL = "critical_full"


class CandidateActionKind(StrEnum):
    """Action proposed for near-capacity remediation."""

    MERGE = "merge"
    ARCHIVE = "archive"


class HitlCandidateStatus(StrEnum):
    """Lifecycle status of a human-in-the-loop candidate proposal."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class MemoryEntryRef(BaseModel):
    """Reference metadata and cryptographic fingerprint of a candidate memory entry."""

    id: str = Field(description="Unique identifier of the memory entry.")
    content: str = Field(description="Raw text content of the memory item.")
    content_hash: str = Field(description="SHA-256 fingerprint for CAS concurrency protection.")
    tags: list[str] = Field(default_factory=list, description="Categorical or semantic tags.")
    created_at: float = Field(description="Creation epoch timestamp.")
    access_count: int = Field(default=0, description="Usage or retrieval frequency count.")


class CapacityStatusReport(BaseModel):
    """Health check report on current memory bank quota utilization."""

    total_entries: int = Field(description="Current count of active stored memory records.")
    max_entries: int = Field(description="Maximum configured entry threshold before overflow.")
    capacity_ratio: float = Field(
        description="Quota utilization ratio ranging from 0.0 to 1.0."
    )
    alert_level: CapacityAlertKind = Field(
        description="Categorized capacity alert level (NORMAL, NEAR_CAPACITY, CRITICAL_FULL)."
    )
    pending_candidate_count: int = Field(
        default=0, description="Number of proposals awaiting human review."
    )
    timestamp: float = Field(description="Epoch timestamp when measurement occurred.")


class HitlCandidateProposal(BaseModel):
    """Human-in-the-loop candidate proposal. Display only by default, never mutated automatically."""

    candidate_id: str = Field(description="Unique identifier for this review proposal.")
    action_kind: CandidateActionKind = Field(
        description="Proposed remediation action (merge or archive)."
    )
    source_entries: list[MemoryEntryRef] = Field(
        description="Original candidate entries targeted by this proposal."
    )
    proposed_content: str = Field(
        description="Synthesized replacement content if merged, or archival rationale."
    )
    reason: str = Field(description="Architectural rationale explaining why remediation is proposed.")
    confidence: float = Field(
        default=0.85, description="Algorithmic confidence score (0.0 - 1.0)."
    )
    status: HitlCandidateStatus = Field(
        default=HitlCandidateStatus.PENDING, description="Current HITL review status."
    )
    created_at: float = Field(description="Epoch timestamp when proposal was generated.")
    resolved_at: float | None = Field(
        default=None, description="Epoch timestamp when human reviewer resolved this."
    )
    reviewer_note: str | None = Field(
        default=None, description="Optional note provided by reviewer."
    )


class CandidateResolutionAction(BaseModel):
    """Decision submitted by human reviewer for a pending candidate proposal."""

    candidate_id: str = Field(description="Target proposal identifier.")
    decision: HitlCandidateStatus = Field(
        description="Resolution decision: APPROVED or REJECTED."
    )
    reviewer_note: str = Field(default="", description="Optional feedback or note.")
