"""Data schemas and contracts for Anti-Semantic-Aliasing and Capacity Governance.

Defines orthogonal source anchors, contrastive discriminator decisions, and capacity
saturation metrics (inspired by Metis / arXiv:2607.26760).

[INPUT]
- pydantic::BaseModel, Field, field_validator (POS: schema definition and validation)
- enum::StrEnum (POS: string-backed decision enums)
- datetime, uuid (POS: timestamping and identity generation)

[OUTPUT]
- MemorySourceAnchor: Explicit multi-dimensional provenance anchor.
- AliasingDecision: Discriminator decision enum (ACCEPT, REJECT_CROSS_DOMAIN, etc.).
- GovernedMemoryEntry: Governed atomic memory unit with provenance and eviction metadata.
- DiscriminatedCandidate: Candidate memory post-discrimination with calibrated score.
- CapacityGovernorMetrics: Quantitative saturation and redundancy metrics.
- EvictionReport: Result of capacity-triggered consolidation and eviction.

[POS]
Foundational data contracts for anti-aliasing defense and capacity saturation governance.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


def _utc_now() -> datetime:
    return datetime.now(UTC)


class AliasingDecision(StrEnum):
    """Decision produced by contrastive anti-semantic-aliasing discriminator."""

    ACCEPT = "accept"
    REJECT_CROSS_DOMAIN = "reject_cross_domain"
    REJECT_ACTOR_CONFLICT = "reject_actor_conflict"
    ISOLATED = "isolated"


class MemorySourceAnchor(BaseModel):
    """Orthogonal metadata anchor pinning a memory to its physical source context."""

    workspace_root: str = Field(default="", description="Workspace root path (e.g. '/app/repo-a')")
    agent_id: str | None = Field(default=None, description="Producing or owning agent ID")
    actor_role: str = Field(default="user", description="Role: user, developer, tester, system")
    session_id: str = Field(default="", description="Source session identifier")
    timestamp: datetime = Field(default_factory=_utc_now, description="Exact creation instant")

    @field_validator("timestamp", mode="before")
    @classmethod
    def _ensure_utc(cls, v: datetime | str | None) -> datetime:
        if v is None:
            return _utc_now()
        if isinstance(v, str):
            v = datetime.fromisoformat(v)
        if v.tzinfo is None:
            return v.replace(tzinfo=UTC)
        return v


class GovernedMemoryEntry(BaseModel):
    """Atomic memory unit under governance, tracking usage, locking, and provenance."""

    entry_id: str = Field(default_factory=lambda: f"gov_{uuid4().hex[:12]}")
    entity: str = Field(..., description="Subject entity key (e.g. 'auth_module', 'db_url')")
    statement: str = Field(..., description="Natural language memory proposition")
    confidence: float = Field(default=0.9, ge=0.0, le=1.0)
    anchor: MemorySourceAnchor = Field(default_factory=MemorySourceAnchor)
    access_count: int = Field(default=1, ge=1, description="Times recalled or accessed")
    is_locked: bool = Field(default=False, description="User-pinned lock immune to eviction")
    created_at: datetime = Field(default_factory=_utc_now)
    last_accessed_at: datetime = Field(default_factory=_utc_now)

    @field_validator("created_at", "last_accessed_at", mode="before")
    @classmethod
    def _ensure_utc(cls, v: datetime | str | None) -> datetime:
        if v is None:
            return _utc_now()
        if isinstance(v, str):
            v = datetime.fromisoformat(v)
        if v.tzinfo is None:
            return v.replace(tzinfo=UTC)
        return v


class DiscriminatedCandidate(BaseModel):
    """Memory recall candidate evaluated through orthogonal negative contrastive verification."""

    entry: GovernedMemoryEntry
    raw_score: float = Field(ge=0.0, le=1.0, description="Raw semantic similarity score")
    calibrated_score: float = Field(ge=0.0, le=1.0, description="Score calibrated by source compatibility")
    decision: AliasingDecision = Field(description="Governor decision on whether to inject or block")
    reason: str = Field(default="", description="Explanatory audit diagnostic")


class CapacityGovernorMetrics(BaseModel):
    """Memory pool capacity, redundancy density, and saturation telemetry."""

    total_active_entries: int
    max_capacity: int
    saturation_ratio: float = Field(ge=0.0, description="Current saturation ratio (active / max)")
    redundancy_density: float = Field(ge=0.0, le=1.0, description="Estimated duplicate entity density")
    is_over_capacity: bool


class EvictionReport(BaseModel):
    """Audit report for capacity consolidation and low-confidence eviction."""

    evicted_entry_ids: list[str] = Field(default_factory=list)
    consolidated_count: int = 0
    freed_slots: int = 0
    new_saturation_ratio: float = 0.0
