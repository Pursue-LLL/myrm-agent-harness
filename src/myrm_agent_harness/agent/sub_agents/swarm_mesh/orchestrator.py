"""SwarmForge Dynamic Topology Orchestrator & Mesh Bus Implementation (Item 55).

Implements declarative multi-agent topology computation (Star, Hierarchical Tree,
Peer-to-Peer Mesh, Pipeline, Ring), seamless dynamic topology switching,
elastic node scaling, live role/state migration, P2P mesh bus message delivery,
and shared blackboard fact governance.

[INPUT]
- __future__
- time
- uuid
- collections
- types

[OUTPUT]
- SwarmTopologyOrchestrator

[POS]
SwarmForge Dynamic Topology Orchestrator & Mesh Bus Implementation (Item 55).
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Mapping

from .types import (
    BlackboardEntry,
    MeshDeliveryStatus,
    MeshEdge,
    MeshMessage,
    MessageRoutingMode,
    MigrationRequest,
    MigrationResult,
    SwarmNode,
    SwarmNodeRole,
    SwarmNodeStatus,
    SwarmTopologyConfig,
    SwarmTopologyState,
    TopologyType,
)


class SwarmTopologyOrchestrator:
    """Orchestrates dynamic multi-agent topologies and mesh communication."""

    def __init__(self, config: SwarmTopologyConfig | None = None) -> None:
        self.config = config or SwarmTopologyConfig(
            topology_id=f"swarm-{uuid.uuid4().hex[:8]}",
            topology_type=TopologyType.STAR,
            max_nodes=16,
            is_adaptive=True,
        )
        self.state = SwarmTopologyState(
            topology_id=self.config.topology_id,
            topology_type=self.config.topology_type,
            is_adaptive=self.config.is_adaptive,
        )
        # Initialize default roster if newly instantiated
        self._init_default_roster()

    def _init_default_roster(self) -> None:
        """Populate initial baseline agent nodes if empty."""
        if self.state.nodes:
            return

        default_nodes = [
            SwarmNode(
                node_id="agent-coordinator-01",
                name="Coordinator Orchestrator",
                role=SwarmNodeRole.COORDINATOR,
                status=SwarmNodeStatus.ACTIVE,
                capabilities=["task_decomposition", "consensus_dispatch", "handoff"],
            ),
            SwarmNode(
                node_id="agent-worker-01",
                name="Primary Engineer Worker",
                role=SwarmNodeRole.WORKER,
                status=SwarmNodeStatus.ACTIVE,
                capabilities=["coding", "debugging", "unit_test"],
            ),
            SwarmNode(
                node_id="agent-worker-02",
                name="Research & Data Worker",
                role=SwarmNodeRole.WORKER,
                status=SwarmNodeStatus.ACTIVE,
                capabilities=["data_extraction", "web_search", "synthesis"],
            ),
            SwarmNode(
                node_id="agent-reviewer-01",
                name="Security & QA Reviewer",
                role=SwarmNodeRole.REVIEWER,
                status=SwarmNodeStatus.ACTIVE,
                capabilities=["lint_audit", "code_review", "security_verification"],
            ),
        ]
        for node in default_nodes:
            self.state.nodes[node.node_id] = node

        self._recompute_connections()

    def compute_edges(
        self,
        topology_type: TopologyType,
        nodes: Mapping[str, SwarmNode],
    ) -> list[MeshEdge]:
        """Compute network connection edges according to declarative topology specification."""
        healthy_nodes = {
            nid: n for nid, n in nodes.items()
            if n.status not in (SwarmNodeStatus.DEGRADED, SwarmNodeStatus.OFFLINE)
        }
        node_ids = list(healthy_nodes.keys())
        edges: list[MeshEdge] = []
        if len(node_ids) < 2:
            return edges

        if topology_type == TopologyType.STAR:
            # Hub-and-spoke: find coordinator or pick first node as hub
            hub = next(
                (nid for nid, n in healthy_nodes.items() if n.role == SwarmNodeRole.COORDINATOR),
                node_ids[0],
            )
            for nid in node_ids:
                if nid != hub:
                    edges.append(MeshEdge(source=hub, target=nid, bidirectional=True))

        elif topology_type == TopologyType.HIERARCHICAL_TREE:
            # Multi-tier tree: coordinator (level 0) -> reviewers/gateways (level 1) -> workers (level 2)
            coordinators = [nid for nid, n in nodes.items() if n.role == SwarmNodeRole.COORDINATOR]
            tier_1 = [
                nid for nid, n in nodes.items()
                if n.role in (SwarmNodeRole.REVIEWER, SwarmNodeRole.GATEWAY)
            ]
            tier_2 = [
                nid for nid, n in nodes.items()
                if n.role in (SwarmNodeRole.WORKER, SwarmNodeRole.SPECIALIST)
            ]
            root = coordinators[0] if coordinators else node_ids[0]

            if tier_1:
                for t1 in tier_1:
                    edges.append(MeshEdge(source=root, target=t1, bidirectional=True))
                # Connect tier 2 workers to tier 1 supervisors in round-robin fashion
                for idx, t2 in enumerate(tier_2):
                    parent = tier_1[idx % len(tier_1)]
                    edges.append(MeshEdge(source=parent, target=t2, bidirectional=True))
            else:
                for leaf in node_ids[1:]:
                    edges.append(MeshEdge(source=root, target=leaf, bidirectional=True))

        elif topology_type == TopologyType.PEER_MESH:
            # Full mesh: every pair connects
            for i in range(len(node_ids)):
                for j in range(i + 1, len(node_ids)):
                    edges.append(MeshEdge(source=node_ids[i], target=node_ids[j], bidirectional=True))

        elif topology_type == TopologyType.PIPELINE:
            # Sequential pipeline: node 0 -> node 1 -> node 2
            for i in range(len(node_ids) - 1):
                edges.append(MeshEdge(source=node_ids[i], target=node_ids[i + 1], bidirectional=False))

        elif topology_type == TopologyType.RING:
            # Closed ring relay
            for i in range(len(node_ids)):
                target_idx = (i + 1) % len(node_ids)
                edges.append(MeshEdge(source=node_ids[i], target=node_ids[target_idx], bidirectional=False))

        return edges

    def _recompute_connections(self) -> None:
        """Update edges and node connected_peers to match the current topology."""
        self.state.edges = self.compute_edges(self.state.topology_type, self.state.nodes)
        peer_map: dict[str, set[str]] = {nid: set() for nid in self.state.nodes}

        for edge in self.state.edges:
            if edge.source in peer_map and edge.target in peer_map:
                peer_map[edge.source].add(edge.target)
                if edge.bidirectional:
                    peer_map[edge.target].add(edge.source)

        for nid, node in self.state.nodes.items():
            node.connected_peers = sorted(peer_map.get(nid, set()))

    def switch_topology(self, target_type: TopologyType) -> SwarmTopologyState:
        """Seamlessly transition swarm topology at runtime while preserving states."""
        self.state.topology_type = target_type
        self.config.topology_type = target_type
        self._recompute_connections()
        return self.state

    def scale_nodes(self, action: str, node: SwarmNode) -> SwarmTopologyState:
        """Scale out (add node) or scale in (retire node) from active swarm."""
        if action == "scale_out":
            self.state.nodes[node.node_id] = node
        elif action == "scale_in":
            self.state.nodes.pop(node.node_id, None)
        self._recompute_connections()
        return self.state

    def migrate_node(self, request: MigrationRequest) -> MigrationResult:
        """Live-migrate an agent node to a target role while retaining state metadata."""
        node = self.state.nodes.get(request.node_id)
        if not node:
            return MigrationResult(
                migration_id=f"mig-{uuid.uuid4().hex[:6]}",
                node_id=request.node_id,
                success=False,
                previous_role=SwarmNodeRole.WORKER,
                current_role=request.target_role,
                details=f"Node {request.node_id} not found in active swarm.",
            )

        previous_role = node.role
        node.status = SwarmNodeStatus.MIGRATING
        node.role = request.target_role
        if request.state_diff:
            node.meta.update(request.state_diff)
        node.status = SwarmNodeStatus.ACTIVE

        self._recompute_connections()
        return MigrationResult(
            migration_id=f"mig-{uuid.uuid4().hex[:6]}",
            node_id=node.node_id,
            success=True,
            previous_role=previous_role,
            current_role=node.role,
            reconnected_peers=list(node.connected_peers),
            details=f"Live migration of node {node.node_id} succeeded. Reason: {request.reason}",
        )

    def send_mesh_message(
        self,
        sender_id: str,
        recipient_id: str,
        routing_mode: MessageRoutingMode,
        channel: str,
        payload: dict[str, str | int | float | bool],
    ) -> MeshMessage:
        """Dispatch a message over the P2P mesh bus (unicast, multicast, or broadcast)."""
        if sender_id not in self.state.nodes:
            raise ValueError(f"Sender '{sender_id}' is not an active node in the swarm mesh.")

        msg = MeshMessage(
            message_id=f"msg-{uuid.uuid4().hex[:8]}",
            sender_id=sender_id,
            recipient_id=recipient_id,
            routing_mode=routing_mode,
            channel=channel,
            payload=payload,
            timestamp=time.time(),
            delivery_status=MeshDeliveryStatus.DELIVERED,
        )

        self.state.recent_messages.append(msg)
        # Keep bounded history of last 50 mesh messages
        if len(self.state.recent_messages) > 50:
            self.state.recent_messages = self.state.recent_messages[-50:]

        return msg

    def read_blackboard(self, key: str | None = None) -> dict[str, BlackboardEntry]:
        """Read facts from the shared blackboard."""
        if key is not None:
            entry = self.state.blackboard.get(key)
            return {key: entry} if entry else {}
        return dict(self.state.blackboard)

    def write_blackboard(
        self,
        key: str,
        value: str,
        author_id: str,
        tags: list[str] | None = None,
    ) -> BlackboardEntry:
        """Write or update a fact in the shared blackboard with version increments."""
        existing = self.state.blackboard.get(key)
        new_version = existing.version + 1 if existing else 1
        entry = BlackboardEntry(
            key=key,
            value=value,
            author_id=author_id,
            version=new_version,
            updated_at=time.time(),
            tags=tags or [],
        )
        self.state.blackboard[key] = entry
        return entry

    def check_health_and_failover(self) -> list[str]:
        """Detect degraded/offline nodes and trigger isolation or recovery."""
        affected: list[str] = []
        for nid, node in list(self.state.nodes.items()):
            if node.status in (SwarmNodeStatus.DEGRADED, SwarmNodeStatus.OFFLINE):
                affected.append(nid)
                # Fail-closed quarantine: decouple peers
                node.connected_peers = []
        if affected:
            self._recompute_connections()
        return affected
