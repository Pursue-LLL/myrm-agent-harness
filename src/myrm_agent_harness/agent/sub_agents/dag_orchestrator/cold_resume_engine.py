"""Checkpoint persistence, cold resume, and bidirectional feedback loopback engine.

[INPUT]
- copy
- datetime
- hashlib
- typing

[OUTPUT]
- NodeNotFoundError
- DagColdResumeEngine

[POS]
Checkpoint persistence, cold resume, and bidirectional feedback loopback engine.

"""

import copy
from datetime import datetime, timezone
import hashlib
from typing import Dict, List, Optional, Set
from myrm_agent_harness.agent.sub_agents.dag_orchestrator.dag_planner import (
    DagDependencyPlanner,
)
from myrm_agent_harness.agent.sub_agents.dag_orchestrator.types import (
    DagCheckpointSnapshot,
    DagNode,
    DagNodeStatus,
)


class NodeNotFoundError(KeyError):
    """Raised when a specified node ID does not exist in the DAG."""


class DagColdResumeEngine:
    """Handles snapshot persistence, cold resume without reprocessing, and bidirectional feedback loops."""

    def __init__(self, planner: Optional[DagDependencyPlanner] = None) -> None:
        self.planner = planner or DagDependencyPlanner()
        self._checkpoints: Dict[str, DagCheckpointSnapshot] = {}

    def save_checkpoint(
        self, dag_id: str, nodes: Dict[str, DagNode]
    ) -> DagCheckpointSnapshot:
        """Persist state snapshot of all DAG nodes."""
        completed_ids = [
            nid for nid, node in nodes.items() if node.status == DagNodeStatus.COMPLETED
        ]
        now_utc = datetime.now(timezone.utc).isoformat()
        snapshot_id = f"snap-{hashlib.sha256(f'{dag_id}:{now_utc}'.encode('utf-8')).hexdigest()[:10]}"

        # Deep copy nodes to freeze state
        frozen_nodes = {nid: copy.deepcopy(node) for nid, node in nodes.items()}
        snapshot = DagCheckpointSnapshot(
            snapshot_id=snapshot_id,
            dag_id=dag_id,
            nodes=frozen_nodes,
            completed_node_ids=completed_ids,
            created_at_utc=now_utc,
        )
        self._checkpoints[dag_id] = snapshot
        return snapshot

    def load_checkpoint(self, dag_id: str) -> Optional[DagCheckpointSnapshot]:
        """Retrieve the latest snapshot for a DAG."""
        return self._checkpoints.get(dag_id)

    def cold_resume(
        self, dag_id: str
    ) -> tuple[Dict[str, DagNode], List[str]]:
        """Restore execution state from persistent checkpoint and compute next ready nodes.

        Never re-executes COMPLETED nodes, preventing wasted compute on crashes/reboots.
        """
        snapshot = self.load_checkpoint(dag_id)
        if not snapshot:
            raise KeyError(f"No checkpoint snapshot found for DAG '{dag_id}'.")

        restored_nodes = {nid: copy.deepcopy(node) for nid, node in snapshot.nodes.items()}
        # If any node was left in RUNNING during crash, reset it to PENDING
        for node in restored_nodes.values():
            if node.status == DagNodeStatus.RUNNING:
                node.status = DagNodeStatus.PENDING

        ready_ids = self.planner.get_ready_nodes(restored_nodes)
        return restored_nodes, ready_ids

    def execute_node_step(
        self, nodes: Dict[str, DagNode], node_id: str
    ) -> DagNode:
        """Simulate execution step of a single ready node and mark it COMPLETED."""
        if node_id not in nodes:
            raise NodeNotFoundError(f"Node '{node_id}' not found in DAG.")

        node = nodes[node_id]
        node.status = DagNodeStatus.COMPLETED
        node.execution_time_ms = 150 + len(node.title) * 5
        node.output_artifact = f"artifact://{node_id}/output_v1.tar.gz"
        node.rejection_feedback = None
        return node

    def reject_and_loopback(
        self,
        nodes: Dict[str, DagNode],
        target_node_id: str,
        feedback: str,
    ) -> Set[str]:
        """Trigger bidirectional review loopback: reject target node and cascade reset downstream nodes.

        Returns set of all affected node IDs (target + cascaded dependents).
        """
        if target_node_id not in nodes:
            raise NodeNotFoundError(f"Node '{target_node_id}' not found in DAG.")

        target_node = nodes[target_node_id]
        target_node.status = DagNodeStatus.REJECTED_LOOPBACK
        target_node.rejection_feedback = feedback
        target_node.output_artifact = None

        # Build forward adjacency to find all downstream transitive dependents
        downstream_map: Dict[str, List[str]] = {nid: [] for nid in nodes}
        for nid, node in nodes.items():
            for dep in node.depends_on:
                if dep in downstream_map:
                    downstream_map[dep].append(nid)

        affected: Set[str] = {target_node_id}
        queue: List[str] = list(downstream_map.get(target_node_id, []))

        while queue:
            curr = queue.pop(0)
            if curr not in affected:
                affected.add(curr)
                # Reset downstream completed or running node back to PENDING
                dep_node = nodes[curr]
                if dep_node.status in (DagNodeStatus.COMPLETED, DagNodeStatus.RUNNING):
                    dep_node.status = DagNodeStatus.PENDING
                    dep_node.output_artifact = None
                queue.extend(downstream_map.get(curr, []))

        return affected

    def clear(self) -> None:
        """Clear all stored checkpoints (for test isolation)."""
        self._checkpoints.clear()
