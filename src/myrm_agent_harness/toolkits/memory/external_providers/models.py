"""Domain models for external memory provider lifecycle and supersedes lineage.

[INPUT]
- Standard library types (dataclasses, datetime, enum).

[OUTPUT]
- MemoryLifecycleStage: 7-step lifecycle state enum.
- MemoryScopeType: scope tier enum (personal, project, team).
- MemoryScopeContext: pre-retrieval scope context DTO.
- EvidenceRecord: immutable evidence tier record.
- DerivedObservationRecord: derived observation tier record with evidence links.
- SupersedesRecord: version evolution linkage record.
- ProviderKind: 8 standard external provider principles.
- ProviderCatalogEntry: provider metadata and capabilities.

[POS]
Domain entities for pluggable external memory providers and lineage governance.
Decouples raw evidence from derived observations and enforces explicit versioning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


def _utc_now() -> datetime:
    """Return current UTC timestamp with timezone."""
    return datetime.now(UTC)


class MemoryLifecycleStage(StrEnum):
    """Seven-stage memory lifecycle state machine."""

    CAPTURE = "capture"
    PROPOSE = "propose"
    VALIDATE = "validate"
    PUBLISH = "publish"
    RECALL = "recall"
    FEEDBACK = "feedback"
    SUPERSEDE = "supersede"
    EXPIRE = "expire"


class MemoryScopeType(StrEnum):
    """Scope tier for physical retrieval isolation."""

    PERSONAL = "personal"
    PROJECT = "project"
    TEAM = "team"


@dataclass(frozen=True, slots=True)
class MemoryScopeContext:
    """Pre-retrieval scope context for hard security filtering."""

    scope_type: MemoryScopeType
    owner_id: str
    project_id: str = ""
    team_id: str = ""
    branch_id: str = ""

    def matches(self, other: MemoryScopeContext) -> bool:
        """Check whether other scope matches this context for isolation."""
        if self.scope_type != other.scope_type:
            return False
        if self.scope_type == MemoryScopeType.PERSONAL:
            return self.owner_id == other.owner_id
        if self.scope_type == MemoryScopeType.PROJECT:
            return self.project_id == other.project_id and self.project_id != ""
        if self.scope_type == MemoryScopeType.TEAM:
            return self.team_id == other.team_id and self.team_id != ""
        return False


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    """Immutable source evidence record representing raw events and dialog turns."""

    evidence_id: str
    session_id: str
    turn_index: int
    source_event_id: str
    content: str
    actor: str
    created_at: datetime = field(default_factory=_utc_now)
    attributes: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DerivedObservationRecord:
    """Derived structured observation linked back to immutable source evidence."""

    observation_id: str
    scope: MemoryScopeContext
    content: str
    category: str
    status: MemoryLifecycleStage
    supporting_evidence_ids: tuple[str, ...]
    proof_count: int
    confidence: float
    freshness: datetime
    supersedes_id: str | None = None
    superseded_by: str | None = None
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)


@dataclass(frozen=True, slots=True)
class SupersedesRecord:
    """Explicit version progression linkage for observation revisions."""

    current_id: str
    previous_id: str
    reason: str
    superseded_at: datetime = field(default_factory=_utc_now)
    rollback_target_id: str | None = None


class ProviderKind(StrEnum):
    """Eight canonical external provider architecture archetypes."""

    HOLOGRAPHIC = "holographic"
    OPEN_VIKING = "open_viking"
    MEM0 = "mem0"
    HINDSIGHT = "hindsight"
    HONCHO = "honcho"
    BYTEROVER = "byterover"
    SUPERMEMORY = "supermemory"
    RETAIN_DB = "retain_db"
    CUSTOM = "custom"


@dataclass(frozen=True, slots=True)
class ProviderCatalogEntry:
    """Metadata descriptor for pluggable memory provider archetypes."""

    kind: ProviderKind
    label: str
    description: str
    is_local_first: bool
    supports_evidence_tier: bool
    default_timeout_ms: int = 300
