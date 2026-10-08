"""Engine managing memory lineage tracker, DAG traversal, and version rollbacks.

[INPUT]
- toolkits.memory.graph_reorganization.models::GraphRelationType, LineageStep, MemoryGraphEdge, MemoryGraphNode, MemoryLineageTrail, MemoryNodeStatus (POS: Domain models and data structures for graph memory reorganization and lineage traceability.)

[OUTPUT]
- MemoryLineageTracker: Core tracker managing memory node lineage DAG, white-box trace trail, and version rollbacks.

[POS]
Engine managing memory lineage tracker, DAG traversal, and version rollbacks.
"""

from __future__ import annotations

from collections import deque
from datetime import UTC, datetime

from myrm_agent_harness.toolkits.memory.graph_reorganization.models import (
    GraphRelationType,
    LineageStep,
    MemoryGraphEdge,
    MemoryGraphNode,
    MemoryLineageTrail,
    MemoryNodeStatus,
)


class MemoryLineageTracker:
    """Core tracker managing memory node lineage DAG, white-box trace trail, and version rollbacks."""

    def __init__(self) -> None:
        self._nodes: dict[str, MemoryGraphNode] = {}
        self._out_edges: dict[str, list[MemoryGraphEdge]] = {}
        self._in_edges: dict[str, list[MemoryGraphEdge]] = {}
        self._root_to_nodes: dict[str, list[str]] = {}

    def register_node(self, node: MemoryGraphNode) -> MemoryGraphNode:
        """Register or update a memory node in the tracker."""
        self._nodes[node.node_id] = node
        root_id = node.lineage_root_id
        if root_id not in self._root_to_nodes:
            self._root_to_nodes[root_id] = []
        if node.node_id not in self._root_to_nodes[root_id]:
            self._root_to_nodes[root_id].append(node.node_id)
        if node.node_id not in self._out_edges:
            self._out_edges[node.node_id] = []
        if node.node_id not in self._in_edges:
            self._in_edges[node.node_id] = []
        return node

    def add_edge(self, edge: MemoryGraphEdge) -> MemoryGraphEdge:
        """Add a directed lineage or semantic relation edge between nodes."""
        if edge.source_node_id not in self._nodes:
            raise KeyError(f"Source node '{edge.source_node_id}' does not exist.")
        if edge.target_node_id not in self._nodes:
            raise KeyError(f"Target node '{edge.target_node_id}' does not exist.")

        self._out_edges.setdefault(edge.source_node_id, []).append(edge)
        self._in_edges.setdefault(edge.target_node_id, []).append(edge)
        return edge

    def get_node(self, node_id: str) -> MemoryGraphNode | None:
        """Fetch memory node by identifier."""
        return self._nodes.get(node_id)

    def list_active_nodes(
        self,
        subject: str | None = None,
    ) -> list[MemoryGraphNode]:
        """List active memory nodes optionally filtered by subject."""
        results: list[MemoryGraphNode] = []
        for node in self._nodes.values():
            if node.status != MemoryNodeStatus.ACTIVE:
                continue
            if subject and node.subject.strip().lower() != subject.strip().lower():
                continue
            results.append(node)
        return sorted(results, key=lambda n: n.updated_at, reverse=True)

    def list_all_nodes(self) -> list[MemoryGraphNode]:
        """List all memory nodes across all lifecycle states."""
        return sorted(list(self._nodes.values()), key=lambda n: n.created_at, reverse=True)

    def list_all_edges(self) -> list[MemoryGraphEdge]:
        """List all registered semantic and lineage edges."""
        edges: list[MemoryGraphEdge] = []
        for edge_list in self._out_edges.values():
            edges.extend(edge_list)
        return sorted(edges, key=lambda e: e.created_at, reverse=True)

    def trace_trail(
        self,
        node_id: str,
        max_depth: int = 10,
    ) -> MemoryLineageTrail:
        """Trace full ancestor origins and downstream impact trail for a given memory node."""
        target_node = self._nodes.get(node_id)
        if not target_node:
            raise KeyError(f"Memory node '{node_id}' not found.")

        ancestors: list[MemoryGraphNode] = []
        descendants: list[MemoryGraphNode] = []
        relevant_edges: list[MemoryGraphEdge] = []
        steps: list[LineageStep] = []
        seen_ancestor_ids: set[str] = {node_id}
        seen_descendant_ids: set[str] = {node_id}
        seen_edge_ids: set[str] = set()

        # Backward traversal: find nodes that current node derived from or superseded
        ancestor_queue: deque[tuple[str, int]] = deque([(node_id, 0)])
        while ancestor_queue:
            curr_id, depth = ancestor_queue.popleft()
            if depth >= max_depth:
                continue
            for edge in self._out_edges.get(curr_id, []):
                if edge.relation_type in (
                    GraphRelationType.SUPERSEDES,
                    GraphRelationType.DERIVED_FROM,
                    GraphRelationType.SUBSUMPTION,
                ):
                    if edge.edge_id not in seen_edge_ids:
                        relevant_edges.append(edge)
                        seen_edge_ids.add(edge.edge_id)
                    tgt_id = edge.target_node_id
                    if tgt_id not in seen_ancestor_ids and tgt_id in self._nodes:
                        seen_ancestor_ids.add(tgt_id)
                        node_found = self._nodes[tgt_id]
                        ancestors.append(node_found)
                        steps.append(
                            LineageStep(
                                step_index=len(steps) + 1,
                                node=node_found,
                                relation_to_target=edge.relation_type,
                                rationale=edge.rationale,
                                timestamp=node_found.created_at,
                            )
                        )
                        ancestor_queue.append((tgt_id, depth + 1))

        # Forward traversal: find nodes that superseded or derived from current node
        descendant_queue: deque[tuple[str, int]] = deque([(node_id, 0)])
        while descendant_queue:
            curr_id, depth = descendant_queue.popleft()
            if depth >= max_depth:
                continue
            for edge in self._in_edges.get(curr_id, []):
                if edge.relation_type in (
                    GraphRelationType.SUPERSEDES,
                    GraphRelationType.DERIVED_FROM,
                ):
                    if edge.edge_id not in seen_edge_ids:
                        relevant_edges.append(edge)
                        seen_edge_ids.add(edge.edge_id)
                    src_id = edge.source_node_id
                    if src_id not in seen_descendant_ids and src_id in self._nodes:
                        seen_descendant_ids.add(src_id)
                        node_found = self._nodes[src_id]
                        descendants.append(node_found)
                        steps.append(
                            LineageStep(
                                step_index=len(steps) + 1,
                                node=node_found,
                                relation_to_target=edge.relation_type,
                                rationale=edge.rationale,
                                timestamp=node_found.created_at,
                            )
                        )
                        descendant_queue.append((src_id, depth + 1))

        sibling_ids = self._root_to_nodes.get(target_node.lineage_root_id, [])
        is_latest = True
        for sib_id in sibling_ids:
            sib = self._nodes.get(sib_id)
            if sib and sib.version > target_node.version and sib.status == MemoryNodeStatus.ACTIVE:
                is_latest = False
                break

        return MemoryLineageTrail(
            target_node=target_node,
            lineage_root_id=target_node.lineage_root_id,
            ancestor_nodes=ancestors,
            descendant_nodes=descendants,
            steps=sorted(steps, key=lambda s: s.timestamp),
            relation_edges=relevant_edges,
            depth=len(ancestors) + len(descendants),
            is_latest=is_latest,
        )

    def revert_to_version(
        self,
        historical_node_id: str,
        new_node_id: str,
        rationale: str = "Rollback to historical memory version",
    ) -> tuple[MemoryGraphNode, MemoryGraphNode]:
        """Rollback active memory state to a historical version by creating an evolved successor version."""
        historical_node = self._nodes.get(historical_node_id)
        if not historical_node:
            raise KeyError(f"Historical node '{historical_node_id}' not found.")

        root_id = historical_node.lineage_root_id
        active_node: MemoryGraphNode | None = None
        max_ver = historical_node.version

        for nid in self._root_to_nodes.get(root_id, []):
            node = self._nodes[nid]
            if node.version > max_ver:
                max_ver = node.version
            if node.status == MemoryNodeStatus.ACTIVE:
                active_node = node

        now_str = datetime.now(UTC).isoformat()

        if active_node:
            active_node.status = MemoryNodeStatus.REVERTED
            active_node.updated_at = now_str

        new_version_node = MemoryGraphNode(
            node_id=new_node_id,
            lineage_root_id=root_id,
            version=max_ver + 1,
            subject=historical_node.subject,
            predicate=historical_node.predicate,
            object_value=historical_node.object_value,
            content=historical_node.content,
            confidence=historical_node.confidence,
            status=MemoryNodeStatus.ACTIVE,
            created_at=now_str,
            updated_at=now_str,
            source_session_id=historical_node.source_session_id,
            evidence_quote=historical_node.evidence_quote,
            metadata={
                **historical_node.metadata,
                "reverted_from_node_id": historical_node_id,
                "rollback_rationale": rationale,
            },
        )
        self.register_node(new_version_node)

        predecessor_id = active_node.node_id if active_node else historical_node.node_id
        edge = MemoryGraphEdge(
            edge_id=f"edge_rev_{new_node_id}_{predecessor_id}",
            source_node_id=new_node_id,
            target_node_id=predecessor_id,
            relation_type=GraphRelationType.SUPERSEDES,
            weight=1.0,
            rationale=rationale,
            created_at=now_str,
        )
        self.add_edge(edge)

        if historical_node_id != predecessor_id:
            derived_edge = MemoryGraphEdge(
                edge_id=f"edge_der_{new_node_id}_{historical_node_id}",
                source_node_id=new_node_id,
                target_node_id=historical_node_id,
                relation_type=GraphRelationType.DERIVED_FROM,
                weight=1.0,
                rationale=f"Derived from historical snapshot v{historical_node.version}",
                created_at=now_str,
            )
            self.add_edge(derived_edge)

        return (active_node or historical_node), new_version_node
