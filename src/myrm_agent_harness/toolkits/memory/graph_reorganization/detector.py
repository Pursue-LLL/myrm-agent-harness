"""Multi-relational detector scanning candidate edges across memory graph nodes.

[INPUT]
- toolkits.memory.graph_reorganization.models::GraphRelationType, MemoryGraphEdge, MemoryGraphNode (POS: Domain models and data structures for graph memory reorganization and lineage traceability.)

[OUTPUT]
- MultiRelationalDetector: Analyzer scanning nodes for contradiction, subsumption, and temporal sequence relations.

[POS]
Multi-relational detector scanning candidate edges across memory graph nodes.
"""

from __future__ import annotations

from dataclasses import dataclass

from myrm_agent_harness.toolkits.memory.graph_reorganization.models import (
    GraphRelationType,
    MemoryGraphEdge,
    MemoryGraphNode,
)


@dataclass(slots=True)
class DetectedEdgeCandidate:
    """Candidate relationship detected between two memory graph nodes."""

    source_node_id: str
    target_node_id: str
    relation_type: GraphRelationType
    confidence: float
    rationale: str


class MultiRelationalDetector:
    """Analyzer scanning nodes for contradiction, subsumption, and temporal sequence relations."""

    def scan_candidates(
        self,
        nodes: list[MemoryGraphNode],
        existing_edges: list[MemoryGraphEdge],
    ) -> list[DetectedEdgeCandidate]:
        """Scan a set of nodes to identify unlinked multi-relational semantic edges."""
        candidates: list[DetectedEdgeCandidate] = []
        connected_pairs: set[tuple[str, str, str]] = {
            (e.source_node_id, e.target_node_id, e.relation_type.value)
            for e in existing_edges
        }

        for i, node_a in enumerate(nodes):
            for node_b in nodes[i + 1 :]:
                # 1. Contradiction Detection
                if (
                    node_a.subject.strip().lower() == node_b.subject.strip().lower()
                    and node_a.predicate.strip().lower() == node_b.predicate.strip().lower()
                    and node_a.object_value.strip().lower() != node_b.object_value.strip().lower()
                ):
                    pair_key = (node_a.node_id, node_b.node_id, GraphRelationType.CONTRADICTION.value)
                    if pair_key not in connected_pairs:
                        candidates.append(
                            DetectedEdgeCandidate(
                                source_node_id=node_a.node_id,
                                target_node_id=node_b.node_id,
                                relation_type=GraphRelationType.CONTRADICTION,
                                confidence=0.95,
                                rationale=(
                                    f"Contradictory values for '{node_a.subject}.{node_a.predicate}': "
                                    f"'{node_a.object_value}' vs '{node_b.object_value}'."
                                ),
                            )
                        )

                # 2. Subsumption Detection
                content_a = node_a.content.lower()
                content_b = node_b.content.lower()
                if (
                    node_a.subject.lower() in node_b.subject.lower()
                    or node_a.object_value.lower() in node_b.object_value.lower()
                ) and len(content_a) < len(content_b):
                    pair_key = (node_a.node_id, node_b.node_id, GraphRelationType.SUBSUMPTION.value)
                    if pair_key not in connected_pairs:
                        candidates.append(
                            DetectedEdgeCandidate(
                                source_node_id=node_a.node_id,
                                target_node_id=node_b.node_id,
                                relation_type=GraphRelationType.SUBSUMPTION,
                                confidence=0.88,
                                rationale=f"General concept '{node_a.subject}' subsumes '{node_b.subject}'.",
                            )
                        )
                elif (
                    node_b.subject.lower() in node_a.subject.lower()
                    or node_b.object_value.lower() in node_a.object_value.lower()
                ) and len(content_b) < len(content_a):
                    pair_key = (node_b.node_id, node_a.node_id, GraphRelationType.SUBSUMPTION.value)
                    if pair_key not in connected_pairs:
                        candidates.append(
                            DetectedEdgeCandidate(
                                source_node_id=node_b.node_id,
                                target_node_id=node_a.node_id,
                                relation_type=GraphRelationType.SUBSUMPTION,
                                confidence=0.88,
                                rationale=f"General concept '{node_b.subject}' subsumes '{node_a.subject}'.",
                            )
                        )

                # 3. Temporal Sequence Detection
                if (
                    node_a.source_session_id
                    and node_a.source_session_id == node_b.source_session_id
                    and node_a.node_id != node_b.node_id
                ):
                    first_n, second_n = (
                        (node_a, node_b) if node_a.created_at <= node_b.created_at else (node_b, node_a)
                    )
                    pair_key = (first_n.node_id, second_n.node_id, GraphRelationType.TEMPORAL_SEQUENCE.value)
                    if pair_key not in connected_pairs:
                        candidates.append(
                            DetectedEdgeCandidate(
                                source_node_id=first_n.node_id,
                                target_node_id=second_n.node_id,
                                relation_type=GraphRelationType.TEMPORAL_SEQUENCE,
                                confidence=0.85,
                                rationale=f"Sequential events within session {node_a.source_session_id}.",
                            )
                        )

        return candidates
