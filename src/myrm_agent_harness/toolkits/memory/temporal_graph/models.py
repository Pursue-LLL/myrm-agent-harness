"""[POS]: src/myrm_agent_harness/toolkits/memory/temporal_graph/models.py
[INPUT]: Dataclass primitives, datetime, and typing structures.
[OUTPUT]: Immutable models for temporal entities, time-aware fact edges, conflict outcomes, and ranked search hits.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class TemporalEntityNode:
    """Named entity node in the temporal knowledge graph."""

    node_id: str
    name: str
    entity_type: str
    attributes: dict[str, str] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class TemporalFactEdge:
    """Time-aware relationship edge with validity intervals and supersession tracking."""

    edge_id: str
    source_id: str
    target_id: str
    predicate: str
    valid_from: datetime = field(default_factory=lambda: datetime.now(UTC))
    valid_until: datetime | None = None
    is_superseded: bool = False
    superseded_by: str | None = None
    confidence_score: float = 1.0
    access_count: int = 0
    last_accessed_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class FactConflictResolutionResult:
    """Outcome report when inserting a fact edge and resolving mutual exclusion conflicts."""

    new_edge: TemporalFactEdge
    superseded_edges: list[TemporalFactEdge]
    is_conflict_detected: bool
    conflict_reason: str


@dataclass(frozen=True)
class TemporalFactHit:
    """Ranked hit from temporal knowledge graph traversal with decay score calculation."""

    edge: TemporalFactEdge
    source_node: TemporalEntityNode
    target_node: TemporalEntityNode
    decayed_score: float
    effective_status: str
