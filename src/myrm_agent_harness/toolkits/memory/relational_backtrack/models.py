"""Types and models for relational backtrack.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- EntityTypeKind: Categorical classification of relational entities.
- TemporalRelationTriplet: A structured entity-action-temporal triplet linking past events with verbatim
  evidence.
- RelationalBacktrackQuery: Query specification for cross-session entity backtracking.
- RelationalBacktrackHit: A candidate relation match pinpointing the associated entity with score.
- RelationalBacktrackResult: Consolidated result returned by the cross-session backtrack engine.

[POS]
Types and models for relational backtrack.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class EntityTypeKind(StrEnum):
    """Categorical classification of relational entities."""

    PERSON = "person"
    CLIENT = "client"
    PROJECT = "project"
    ORGANIZATION = "organization"
    LOCATION = "location"
    TOOL = "tool"


@dataclass(frozen=True)
class TemporalRelationTriplet:
    """A structured entity-action-temporal triplet linking past events with verbatim evidence."""

    triplet_id: str
    subject: str
    predicate_action: str  # Canonical action, e.g. "eat_hotpot"
    target_entity: str     # Target object, e.g. "李总"
    target_entity_type: EntityTypeKind
    temporal_anchor: str   # Absolute or resolved date, e.g. "2026-10-15"
    session_id: str
    message_id: str
    verbatim_quote: str    # Verbatim dialogue fragment pinning the claim
    action_synonyms: list[str] = field(default_factory=list)
    confidence: float = 1.0
    created_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )


@dataclass(frozen=True)
class RelationalBacktrackQuery:
    """Query specification for cross-session entity backtracking."""

    action_cue: str  # e.g., "打边炉", "签约"
    target_entity_type: EntityTypeKind | None = None
    session_id_scope: str | None = None
    min_confidence: float = 0.5


@dataclass(frozen=True)
class RelationalBacktrackHit:
    """A candidate relation match pinpointing the associated entity with score."""

    triplet: TemporalRelationTriplet
    matched_cue: str
    match_score: float


@dataclass(frozen=True)
class RelationalBacktrackResult:
    """Consolidated result returned by the cross-session backtrack engine."""

    hits: list[RelationalBacktrackHit]
    total_found: int
    inferred_answer: str | None
