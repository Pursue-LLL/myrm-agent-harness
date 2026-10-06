# [POS] toolkits/memory/graph_rrf/types.py
# [INPUT] None
# [OUTPUT] EntityNode, RelationEdge, GraphTraversalPath, GraphTraversalResult, VectorHit, GraphHit, FusedMemoryHit, RRFConfig

"""Data models and contract types for Knowledge Graph and Vector RRF Fusion Memory Engine."""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass(frozen=True)
class EntityNode:
    """Represents a named entity in the memory knowledge graph."""

    id: str
    name: str
    entity_type: str
    properties: dict[str, str] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class RelationEdge:
    """Represents a directional relationship between two entities."""

    id: str
    source_id: str
    target_id: str
    relation_type: str
    weight: float = 1.0
    properties: dict[str, str] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class GraphTraversalPath:
    """Represents an edge traversed during graph expansion."""

    source_id: str
    target_id: str
    relation_type: str
    depth: int


@dataclass(frozen=True)
class GraphTraversalResult:
    """Result of breadth-first traversal starting from seed entities."""

    nodes: list[EntityNode]
    edges: list[RelationEdge]
    paths: list[GraphTraversalPath]
    associated_memory_ids: list[str]


@dataclass(frozen=True)
class VectorHit:
    """Ranked hit from semantic vector search channel."""

    memory_id: str
    content: str
    score: float
    rank: int


@dataclass(frozen=True)
class GraphHit:
    """Ranked hit from knowledge graph traversal channel."""

    memory_id: str
    entity_id: str
    content: str
    hop: int
    path: list[str]
    score: float
    rank: int


@dataclass(frozen=True)
class FusedMemoryHit:
    """Memory item ranked and unified by Reciprocal Rank Fusion."""

    memory_id: str
    content: str
    fused_score: float
    vector_rank: int | None
    graph_rank: int | None
    hit_sources: list[str]
    explanation: dict[str, str | int | float | list[str]] = field(
        default_factory=dict
    )


@dataclass(frozen=True)
class RRFConfig:
    """Hyperparameters and operational limits for dual-channel RRF."""

    k: int = 60
    vector_weight: float = 1.0
    graph_weight: float = 1.0
    max_graph_hops: int = 2
    top_k: int = 10
    max_nodes_visited: int = 500
