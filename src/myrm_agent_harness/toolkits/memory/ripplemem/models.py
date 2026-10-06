"""Data models for RippleMem sparse event graph and budgeted active recall.

[INPUT]
- Standard library types (dataclasses, datetime, enum).

[OUTPUT]
- NormalizedEventUnit: Core event unit m=(r, v, p, l, t, c) with clues.
- GraphEdgeType: Edge taxonomy for semantic and structural connections.
- SparseEventEdge: Lightweight typed edge between normalized event nodes.
- MissingSupportTarget: Inferred evidence gap specification.
- RippleSpreadBudget: Budget configuration for directional graph spreading.
- MultiHopProvenanceTrace: Structured multi-hop attribution chain.
- RippleRecallResult: Complete result package of active recall execution.

[POS]
Domain models defining atomic normalized event units, sparse graph topology,
and active recall controller payloads for multi-session distributed reasoning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


def _utc_now() -> datetime:
    """Return timezone-aware current UTC timestamp."""
    return datetime.now(UTC)


class GraphEdgeType(StrEnum):
    """Taxonomy of edges connecting normalized event units in the sparse graph."""

    SEMANTIC = "semantic"
    PARTICIPANT = "participant"
    LOCATION = "location"
    TEMPORAL = "temporal"
    CONCEPT = "concept"


@dataclass(slots=True)
class NormalizedEventUnit:
    """Normalized atomic event representation m=(r, v, p, l, t, c).

    Attributes:
        id: Unique deterministic or generated identifier of the event.
        representation: Canonical factual representation with pronouns resolved.
        embedding: Semantic vector embedding of the canonical representation.
        participants: Set of person or actor entity names mentioned in the event.
        locations: Set of physical or virtual locations mentioned in the event.
        time_span: Normalized absolute temporal range or timestamp string.
        concepts: Set of general domain concepts, topics, or technical keywords.
        raw_text: Original raw utterance or snippet for provenance display.
        session_id: Source session identifier where this event originated.
        created_at: Absolute creation timestamp of the underlying event.
        metadata: Type-safe key-value string metadata for domain context.
    """

    id: str
    representation: str
    embedding: list[float] = field(default_factory=list)
    participants: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    time_span: str = ""
    concepts: list[str] = field(default_factory=list)
    raw_text: str = ""
    session_id: str = ""
    created_at: datetime = field(default_factory=_utc_now)
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class SparseEventEdge:
    """Lightweight directed or undirected edge between two event units."""

    source_id: str
    target_id: str
    edge_type: GraphEdgeType
    weight: float = 1.0
    clue_value: str = ""
    created_at: datetime = field(default_factory=_utc_now)


@dataclass(slots=True)
class MissingSupportTarget:
    """Specification of an inferred missing support target from recall controller."""

    target_entity: str
    relation_aspect: str
    reasoning: str = ""
    priority: float = 1.0


@dataclass(slots=True)
class RippleSpreadBudget:
    """Resource constraints bounding the directional ripple spreading process."""

    max_hops: int = 2
    max_events: int = 8
    max_token_budget: int = 1500
    timeout_ms: float = 300.0
    max_degree_per_node: int = 16


@dataclass(slots=True)
class MultiHopProvenanceStep:
    """Single transition step within the multi-hop attribution chain."""

    from_event_id: str
    to_event_id: str
    edge_type: GraphEdgeType
    clue: str
    hop_depth: int
    event_summary: str


@dataclass(slots=True)
class MultiHopProvenanceTrace:
    """Complete provenance trace explaining how missing evidence was resolved."""

    query: str
    anchor_event_ids: list[str]
    missing_targets: list[MissingSupportTarget]
    steps: list[MultiHopProvenanceStep] = field(default_factory=list)
    resolved_event_ids: list[str] = field(default_factory=list)
    saturated_fast_path: bool = False
    duration_ms: float = 0.0


@dataclass(slots=True)
class RippleRecallResult:
    """Final package produced by the budgeted active recall controller."""

    events: list[NormalizedEventUnit]
    provenance: MultiHopProvenanceTrace
    saturated_fast_path: bool
    budget_exhausted: bool = False
