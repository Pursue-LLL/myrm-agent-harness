"""Types and models for fact supersession.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- TemporalFactStatus: Lifecycle status of a temporal fact in the supersession ledger.
- TemporalFactRecord: Core domain model representing a factual assertion with explicit valid-time interval.
- ContradictionQuarantineItem: Quarantine entry holding a low-confidence contradictory fact candidate pending
  human review.
- DialecticRecallProjection: Explainable recall payload projecting active facts alongside their superseded
  lineage.

[POS]
Types and models for fact supersession.
"""

# [POS]: src/myrm_agent_harness/toolkits/memory/fact_supersession/models.py
# [INPUT]: None (Domain models for Fact Supersession, Temporal Validity, and Contradiction Quarantine)
# [OUTPUT]: TemporalFactStatus, TemporalFactRecord, ContradictionQuarantineItem, DialecticRecallProjection

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class TemporalFactStatus(StrEnum):
    """Lifecycle status of a temporal fact in the supersession ledger."""

    ACTIVE = "active"
    SUPERSEDED = "superseded"
    QUARANTINED = "quarantined"
    ARCHIVED = "archived"


@dataclass
class TemporalFactRecord:
    """Core domain model representing a factual assertion with explicit valid-time interval."""

    fact_id: str
    subject: str
    predicate: str
    object_value: str
    valid_from: str
    valid_until: str | None = None
    superseded_by: str | None = None
    confidence: float = 1.0
    status: TemporalFactStatus = TemporalFactStatus.ACTIVE
    source_session_id: str | None = None
    evidence_quote: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass
class ContradictionQuarantineItem:
    """Quarantine entry holding a low-confidence contradictory fact candidate pending human review."""

    quarantine_id: str
    new_fact: TemporalFactRecord
    conflicting_fact_id: str
    conflict_score: float
    detected_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    status: str = "quarantined"  # "quarantined", "approved", "rejected"


@dataclass
class DialecticRecallProjection:
    """Explainable recall payload projecting active facts alongside their superseded lineage."""

    active_facts: list[TemporalFactRecord] = field(default_factory=list)
    superseded_lineage: dict[str, list[TemporalFactRecord]] = field(
        default_factory=dict
    )
    as_of_time: str | None = None
    total_matched: int = 0
