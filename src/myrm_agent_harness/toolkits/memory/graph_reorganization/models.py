"""Domain models and data structures for graph memory reorganization and lineage traceability.

[INPUT]
- None (self-contained standard library typing and dataclasses)

[OUTPUT]
- GraphRelationType: Multi-relational semantic graph edge classification.
- MemoryNodeStatus: Lifecycle status of memory graph nodes.
- MemoryGraphNode: Knowledge graph memory node with lineage tracking attributes.
- MemoryGraphEdge: Directed multi-relational semantic graph edge.
- LineageStep: Individual step or milestone in a node's lineage evolution trajectory.
- MemoryLineageTrail: White-box explainable lineage trace across ancestors and descendants.
- ReorganizationReport: Summary outcome report of an automated graph reorganization batch pass.

[POS]
Domain models and data structures for graph memory reorganization and lineage traceability.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class GraphRelationType(StrEnum):
    """Multi-relational semantic edge types."""

    SUBSUMPTION = "subsumption"
    TEMPORAL_SEQUENCE = "temporal_sequence"
    DEDUCTION = "deduction"
    SUPERSEDES = "supersedes"
    DERIVED_FROM = "derived_from"
    CONTRADICTION = "contradiction"
    MERGED_INTO = "merged_into"


class MemoryNodeStatus(StrEnum):
    """Lifecycle status of memory graph nodes."""

    ACTIVE = "active"
    SUPERSEDED = "superseded"
    ARCHIVED = "archived"
    REVERTED = "reverted"


@dataclass(slots=True)
class MemoryGraphNode:
    """Knowledge graph memory node preserving lineage and version identity."""

    node_id: str
    lineage_root_id: str
    version: int
    subject: str
    predicate: str
    object_value: str
    content: str
    confidence: float = 1.0
    status: MemoryNodeStatus = MemoryNodeStatus.ACTIVE
    created_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )
    updated_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )
    source_session_id: str | None = None
    evidence_quote: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class MemoryGraphEdge:
    """Directed multi-relational semantic graph edge connecting memory nodes."""

    edge_id: str
    source_node_id: str
    target_node_id: str
    relation_type: GraphRelationType
    weight: float = 1.0
    rationale: str = ""
    created_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )


@dataclass(slots=True)
class LineageStep:
    """Individual step or milestone in a node's lineage evolution trajectory."""

    step_index: int
    node: MemoryGraphNode
    relation_to_target: GraphRelationType | None
    rationale: str
    timestamp: str


@dataclass(slots=True)
class MemoryLineageTrail:
    """White-box explainable lineage trace across ancestors, descendants, and steps."""

    target_node: MemoryGraphNode
    lineage_root_id: str
    ancestor_nodes: list[MemoryGraphNode] = field(default_factory=list)
    descendant_nodes: list[MemoryGraphNode] = field(default_factory=list)
    steps: list[LineageStep] = field(default_factory=list)
    relation_edges: list[MemoryGraphEdge] = field(default_factory=list)
    depth: int = 0
    is_latest: bool = True


@dataclass(slots=True)
class ReorganizationReport:
    """Summary outcome report of an automated graph reorganization batch pass."""

    batch_id: str
    analyzed_nodes_count: int
    created_edges_count: int
    superseded_nodes_count: int
    deductions_count: int
    edges: list[MemoryGraphEdge] = field(default_factory=list)
    created_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )
