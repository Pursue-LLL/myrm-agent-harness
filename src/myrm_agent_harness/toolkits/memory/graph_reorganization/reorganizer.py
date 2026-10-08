"""Graph memory reorganization engine synthesizing multi-relational edges and managing supersession.

[INPUT]
- toolkits.memory.graph_reorganization.detector::MultiRelationalDetector (POS: Analyzer scanning nodes for contradiction, subsumption, and temporal sequence relations.)
- toolkits.memory.graph_reorganization.lineage_engine::MemoryLineageTracker (POS: Core tracker managing memory node lineage DAG, white-box trace trail, and version rollbacks.)
- toolkits.memory.graph_reorganization.models::GraphRelationType, MemoryGraphEdge, MemoryGraphNode, MemoryNodeStatus, ReorganizationReport (POS: Domain models and data structures for graph memory reorganization and lineage traceability.)

[OUTPUT]
- GraphMemoryReorganizationEngine: High-level orchestration engine executing graph reorganization passes and lineage evolution.

[POS]
Graph memory reorganization engine synthesizing multi-relational edges and managing supersession.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from myrm_agent_harness.toolkits.memory.graph_reorganization.detector import (
    MultiRelationalDetector,
)
from myrm_agent_harness.toolkits.memory.graph_reorganization.lineage_engine import (
    MemoryLineageTracker,
)
from myrm_agent_harness.toolkits.memory.graph_reorganization.models import (
    GraphRelationType,
    MemoryGraphEdge,
    MemoryGraphNode,
    MemoryNodeStatus,
    ReorganizationReport,
)


class GraphMemoryReorganizationEngine:
    """High-level orchestration engine executing graph reorganization passes and lineage evolution."""

    def __init__(
        self,
        tracker: MemoryLineageTracker | None = None,
        detector: MultiRelationalDetector | None = None,
    ) -> None:
        self._tracker = tracker or MemoryLineageTracker()
        self._detector = detector or MultiRelationalDetector()

    @property
    def tracker(self) -> MemoryLineageTracker:
        """Access underlying memory lineage tracker."""
        return self._tracker

    def record_evolution(
        self,
        superseded_node_id: str,
        new_node: MemoryGraphNode,
        rationale: str = "Memory evolved with updated preferences or factual supersession.",
    ) -> tuple[MemoryGraphNode, MemoryGraphNode, MemoryGraphEdge]:
        """Atomically record an evolved memory node replacing an existing node without physical deletion."""
        old_node = self._tracker.get_node(superseded_node_id)
        if not old_node:
            raise KeyError(f"Target node '{superseded_node_id}' to supersede not found.")

        now_str = datetime.now(UTC).isoformat()
        old_node.status = MemoryNodeStatus.SUPERSEDED
        old_node.updated_at = now_str

        # Propagate lineage root and increment version monotonically
        new_node.lineage_root_id = old_node.lineage_root_id
        new_node.version = old_node.version + 1
        new_node.status = MemoryNodeStatus.ACTIVE
        new_node.created_at = now_str
        new_node.updated_at = now_str
        self._tracker.register_node(new_node)

        edge = MemoryGraphEdge(
            edge_id=f"edge_sup_{new_node.node_id}_{old_node.node_id}",
            source_node_id=new_node.node_id,
            target_node_id=old_node.node_id,
            relation_type=GraphRelationType.SUPERSEDES,
            weight=1.0,
            rationale=rationale,
            created_at=now_str,
        )
        self._tracker.add_edge(edge)

        return old_node, new_node, edge

    def run_reorganization_batch(self, min_confidence: float = 0.8) -> ReorganizationReport:
        """Scan active nodes and automatically generate multi-relational edges."""
        active_nodes = self._tracker.list_active_nodes()
        existing_edges = self._tracker.list_all_edges()
        candidates = self._detector.scan_candidates(active_nodes, existing_edges)

        created_edges: list[MemoryGraphEdge] = []
        now_str = datetime.now(UTC).isoformat()
        batch_id = f"reorg_{uuid.uuid4().hex[:8]}"

        for cand in candidates:
            if cand.confidence < min_confidence:
                continue

            edge = MemoryGraphEdge(
                edge_id=f"edge_{cand.source_node_id[:6]}_{cand.target_node_id[:6]}_{uuid.uuid4().hex[:4]}",
                source_node_id=cand.source_node_id,
                target_node_id=cand.target_node_id,
                relation_type=cand.relation_type,
                weight=cand.confidence,
                rationale=cand.rationale,
                created_at=now_str,
            )
            self._tracker.add_edge(edge)
            created_edges.append(edge)

        return ReorganizationReport(
            batch_id=batch_id,
            analyzed_nodes_count=len(active_nodes),
            created_edges_count=len(created_edges),
            superseded_nodes_count=0,
            deductions_count=0,
            edges=created_edges,
            created_at=now_str,
        )
