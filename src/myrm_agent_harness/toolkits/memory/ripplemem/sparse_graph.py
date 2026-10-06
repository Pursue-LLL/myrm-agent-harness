"""Dual-edge sparse event graph store for RippleMem architecture.

[INPUT]
- NormalizedEventUnit, SparseEventEdge, GraphEdgeType from .models.
- Standard library modules (math, datetime, collections, logging).

[OUTPUT]
- DualEdgeSparseGraphStore: High-performance sparse graph index with degree pruning.

[POS]
Maintains semantic and structural edges connecting normalized event units.
Implements bounded incremental linking and degree-pruned neighbor retrieval.
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from datetime import UTC, datetime

from myrm_agent_harness.toolkits.memory.ripplemem.models import (
    GraphEdgeType,
    NormalizedEventUnit,
    SparseEventEdge,
)

logger = logging.getLogger(__name__)


def _cosine_similarity(vec1: list[float], vec2: list[float]) -> float:
    """Compute cosine similarity between two float vectors safely."""
    if not vec1 or not vec2 or len(vec1) != len(vec2):
        return 0.0
    dot_product = sum(a * b for a, b in zip(vec1, vec2, strict=False))
    norm_a = math.sqrt(sum(a * a for a in vec1))
    norm_b = math.sqrt(sum(b * b for b in vec2))
    if norm_a <= 1e-9 or norm_b <= 1e-9:
        return 0.0
    return max(0.0, min(1.0, dot_product / (norm_a * norm_b)))


class DualEdgeSparseGraphStore:
    """Stores normalized event units and manages dual-edge sparse topologies."""

    def __init__(
        self,
        *,
        semantic_threshold: float = 0.72,
        half_life_days: float = 30.0,
        max_degree_per_node: int = 16,
    ) -> None:
        self._semantic_threshold = semantic_threshold
        self._half_life_days = half_life_days
        self._max_degree_per_node = max_degree_per_node

        self._events: dict[str, NormalizedEventUnit] = {}
        self._outgoing_edges: dict[str, list[SparseEventEdge]] = defaultdict(list)
        self._incoming_edges: dict[str, list[SparseEventEdge]] = defaultdict(list)

        # Inverted clue indexes for instant O(1) clue-based seed anchor recall
        self._participant_index: dict[str, set[str]] = defaultdict(set)
        self._location_index: dict[str, set[str]] = defaultdict(set)
        self._concept_index: dict[str, set[str]] = defaultdict(set)

    def add_event(
        self,
        event: NormalizedEventUnit,
        *,
        auto_link_neighbors: bool = True,
    ) -> None:
        """Register a normalized event unit and incrementally build local sparse edges."""
        self._events[event.id] = event

        # Index clues
        for p in event.participants:
            self._participant_index[p.lower()].add(event.id)
        for loc in event.locations:
            self._location_index[loc.lower()].add(event.id)
        for c in event.concepts:
            self._concept_index[c.lower()].add(event.id)

        if auto_link_neighbors:
            self._link_structural_clues(event)
            if event.embedding:
                self._link_semantic_neighbors(event)

    def get_event(self, event_id: str) -> NormalizedEventUnit | None:
        """Fetch a registered event unit by unique identifier."""
        return self._events.get(event_id)

    def get_all_events(self) -> list[NormalizedEventUnit]:
        """Fetch all stored events."""
        return list(self._events.values())

    def get_pruned_neighbors(
        self,
        event_id: str,
        *,
        filter_edge_types: set[GraphEdgeType] | None = None,
        query_vector: list[float] | None = None,
        max_degree: int | None = None,
    ) -> list[tuple[NormalizedEventUnit, SparseEventEdge]]:
        """Fetch outgoing neighbors with degree truncation to prevent diffusion avalanches."""
        edges = self._outgoing_edges.get(event_id, [])
        if not edges:
            return []

        limit = max_degree or self._max_degree_per_node
        candidates: list[tuple[NormalizedEventUnit, SparseEventEdge]] = []

        now_utc = datetime.now(UTC)

        for edge in edges:
            if filter_edge_types and edge.edge_type not in filter_edge_types:
                continue
            target_node = self._events.get(edge.target_id)
            if target_node is None:
                continue

            # Temporal edge weight decay
            age_days = max(0.0, (now_utc - target_node.created_at).total_seconds() / 86400.0)
            decay_factor = math.pow(0.5, age_days / self._half_life_days)
            effective_weight = edge.weight * decay_factor

            # Modulate with query embedding similarity if provided
            if query_vector and target_node.embedding:
                q_sim = _cosine_similarity(query_vector, target_node.embedding)
                effective_weight = 0.5 * effective_weight + 0.5 * q_sim

            decayed_edge = SparseEventEdge(
                source_id=edge.source_id,
                target_id=edge.target_id,
                edge_type=edge.edge_type,
                weight=effective_weight,
                clue_value=edge.clue_value,
                created_at=edge.created_at,
            )
            candidates.append((target_node, decayed_edge))

        # Super-node pruning: Sort descending by effective weight and truncate
        candidates.sort(key=lambda pair: pair[1].weight, reverse=True)
        return candidates[:limit]

    def find_events_by_clue(
        self,
        *,
        participant: str = "",
        location: str = "",
        concept: str = "",
    ) -> list[NormalizedEventUnit]:
        """Query event units by exact clue matching against inverted indexes."""
        matched_ids: set[str] = set()

        if participant:
            matched_ids.update(self._participant_index.get(participant.lower(), set()))
        if location:
            matched_ids.update(self._location_index.get(location.lower(), set()))
        if concept:
            matched_ids.update(self._concept_index.get(concept.lower(), set()))

        results: list[NormalizedEventUnit] = []
        for eid in matched_ids:
            evt = self._events.get(eid)
            if evt is not None:
                results.append(evt)
        return results

    def _link_structural_clues(self, new_event: NormalizedEventUnit) -> None:
        """Create bidirectional structural edges between events sharing typed clues."""
        linked_targets: set[str] = set()

        for p in new_event.participants:
            for peer_id in self._participant_index.get(p.lower(), set()):
                if peer_id != new_event.id and peer_id not in linked_targets:
                    self._create_bidirectional_edge(
                        new_event.id,
                        peer_id,
                        GraphEdgeType.PARTICIPANT,
                        weight=0.9,
                        clue=p,
                    )
                    linked_targets.add(peer_id)

        for c in new_event.concepts:
            for peer_id in self._concept_index.get(c.lower(), set()):
                if peer_id != new_event.id and peer_id not in linked_targets:
                    self._create_bidirectional_edge(
                        new_event.id,
                        peer_id,
                        GraphEdgeType.CONCEPT,
                        weight=0.8,
                        clue=c,
                    )
                    linked_targets.add(peer_id)

    def _link_semantic_neighbors(self, new_event: NormalizedEventUnit) -> None:
        """Create semantic edges towards existing nodes exceeding cosine similarity threshold."""
        for peer_id, peer_event in self._events.items():
            if peer_id == new_event.id or not peer_event.embedding:
                continue
            sim = _cosine_similarity(new_event.embedding, peer_event.embedding)
            if sim >= self._semantic_threshold:
                self._create_bidirectional_edge(
                    new_event.id,
                    peer_id,
                    GraphEdgeType.SEMANTIC,
                    weight=sim,
                    clue=f"sim:{sim:.2f}",
                )

    def _create_bidirectional_edge(
        self,
        node_a: str,
        node_b: str,
        edge_type: GraphEdgeType,
        *,
        weight: float,
        clue: str,
    ) -> None:
        """Register symmetric sparse edges connecting node_a and node_b."""
        now = datetime.now(UTC)
        edge_ab = SparseEventEdge(
            source_id=node_a,
            target_id=node_b,
            edge_type=edge_type,
            weight=weight,
            clue_value=clue,
            created_at=now,
        )
        edge_ba = SparseEventEdge(
            source_id=node_b,
            target_id=node_a,
            edge_type=edge_type,
            weight=weight,
            clue_value=clue,
            created_at=now,
        )
        self._outgoing_edges[node_a].append(edge_ab)
        self._incoming_edges[node_b].append(edge_ab)
        self._outgoing_edges[node_b].append(edge_ba)
        self._incoming_edges[node_a].append(edge_ba)
