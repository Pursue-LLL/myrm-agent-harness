"""Unit tests for SwarmForge Dynamic Topology Orchestrator & Mesh Bus (Item 55)."""

import pytest

from myrm_agent_harness.agent.sub_agents.swarm_mesh import (
    MessageRoutingMode,
    MigrationRequest,
    SwarmNode,
    SwarmNodeRole,
    SwarmNodeStatus,
    SwarmTopologyOrchestrator,
    TopologyType,
)


def test_default_roster_initialization_star() -> None:
    """Verify default initial swarm star topology and hub connections."""
    orchestrator = SwarmTopologyOrchestrator()
    state = orchestrator.state

    assert state.topology_type == TopologyType.STAR
    assert len(state.nodes) == 4
    assert "agent-coordinator-01" in state.nodes
    assert len(state.edges) == 3

    coordinator = state.nodes["agent-coordinator-01"]
    assert len(coordinator.connected_peers) == 3


def test_compute_edges_hierarchical_tree() -> None:
    """Verify hierarchical multi-tier tree edge distribution."""
    orchestrator = SwarmTopologyOrchestrator()
    tree_state = orchestrator.switch_topology(TopologyType.HIERARCHICAL_TREE)

    assert tree_state.topology_type == TopologyType.HIERARCHICAL_TREE
    # Root coordinator connected to reviewer, reviewer connected to workers
    edges = tree_state.edges
    assert len(edges) >= 3

    sources_and_targets = [(e.source, e.target) for e in edges]
    assert ("agent-coordinator-01", "agent-reviewer-01") in sources_and_targets


def test_compute_edges_peer_mesh() -> None:
    """Verify peer-to-peer full mesh edge count (N*(N-1)/2)."""
    orchestrator = SwarmTopologyOrchestrator()
    mesh_state = orchestrator.switch_topology(TopologyType.PEER_MESH)

    # 4 nodes -> 4 * 3 / 2 = 6 undirected edges
    assert len(mesh_state.edges) == 6
    for node in mesh_state.nodes.values():
        assert len(node.connected_peers) == 3


def test_compute_edges_pipeline_and_ring() -> None:
    """Verify sequential pipeline and closed ring edge topologies."""
    orchestrator = SwarmTopologyOrchestrator()

    # Pipeline
    pipeline_state = orchestrator.switch_topology(TopologyType.PIPELINE)
    assert len(pipeline_state.edges) == 3

    # Ring
    ring_state = orchestrator.switch_topology(TopologyType.RING)
    assert len(ring_state.edges) == 4


def test_switch_topology_seamless_preservation() -> None:
    """Verify switching topology preserves existing nodes, messages, and blackboard state."""
    orchestrator = SwarmTopologyOrchestrator()
    orchestrator.write_blackboard("system.benchmark", "pass_99", "agent-coordinator-01")

    # Send a message
    orchestrator.send_mesh_message(
        sender_id="agent-coordinator-01",
        recipient_id="*",
        routing_mode=MessageRoutingMode.BROADCAST,
        channel="announcements",
        payload={"topic": "prepare_pipeline"},
    )

    # Switch to Pipeline
    new_state = orchestrator.switch_topology(TopologyType.PIPELINE)
    assert new_state.topology_type == TopologyType.PIPELINE
    assert "system.benchmark" in new_state.blackboard
    assert len(new_state.recent_messages) == 1


def test_scale_nodes_out_and_in() -> None:
    """Verify elastic scaling out and scaling in of nodes."""
    orchestrator = SwarmTopologyOrchestrator()
    new_node = SwarmNode(
        node_id="agent-specialist-01",
        name="Performance Optimization Specialist",
        role=SwarmNodeRole.SPECIALIST,
        status=SwarmNodeStatus.ACTIVE,
    )

    # Scale out
    state_out = orchestrator.scale_nodes("scale_out", new_node)
    assert len(state_out.nodes) == 5
    assert "agent-specialist-01" in state_out.nodes

    # Scale in
    state_in = orchestrator.scale_nodes("scale_in", new_node)
    assert len(state_in.nodes) == 4
    assert "agent-specialist-01" not in state_in.nodes


def test_migrate_node_live_role_and_state() -> None:
    """Verify live node migration preserves state metadata and updates role."""
    orchestrator = SwarmTopologyOrchestrator()
    req = MigrationRequest(
        node_id="agent-worker-01",
        target_role=SwarmNodeRole.REVIEWER,
        state_diff={"assigned_audits": "module_mesh"},
        reason="Promoting worker to reviewer for high-traffic workload",
    )

    res = orchestrator.migrate_node(req)
    assert res.success is True
    assert res.previous_role == SwarmNodeRole.WORKER
    assert res.current_role == SwarmNodeRole.REVIEWER

    migrated_node = orchestrator.state.nodes["agent-worker-01"]
    assert migrated_node.role == SwarmNodeRole.REVIEWER
    assert migrated_node.meta.get("assigned_audits") == "module_mesh"


def test_send_mesh_message_modes() -> None:
    """Verify unicast, multicast, and broadcast message routing over the mesh bus."""
    orchestrator = SwarmTopologyOrchestrator()

    # Unicast
    msg_uni = orchestrator.send_mesh_message(
        sender_id="agent-coordinator-01",
        recipient_id="agent-worker-01",
        routing_mode=MessageRoutingMode.UNICAST,
        channel="direct_task",
        payload={"task_id": "T-100", "priority": 1},
    )
    assert msg_uni.routing_mode == MessageRoutingMode.UNICAST
    assert msg_uni.recipient_id == "agent-worker-01"

    # Broadcast
    msg_broad = orchestrator.send_mesh_message(
        sender_id="agent-worker-01",
        recipient_id="*",
        routing_mode=MessageRoutingMode.BROADCAST,
        channel="team_sync",
        payload={"event": "worker_ready"},
    )
    assert msg_broad.routing_mode == MessageRoutingMode.BROADCAST

    # Invalid sender raises
    with pytest.raises(ValueError, match="not an active node"):
        orchestrator.send_mesh_message(
            sender_id="ghost-agent",
            recipient_id="*",
            routing_mode=MessageRoutingMode.BROADCAST,
            channel="team_sync",
            payload={},
        )


def test_blackboard_write_read_versioning() -> None:
    """Verify shared blackboard facts and incremental versioning."""
    orchestrator = SwarmTopologyOrchestrator()

    e1 = orchestrator.write_blackboard("goal.spec", "v1.0-draft", "agent-coordinator-01", ["spec", "v1"])
    assert e1.version == 1
    assert e1.value == "v1.0-draft"

    e2 = orchestrator.write_blackboard("goal.spec", "v1.1-approved", "agent-reviewer-01", ["spec", "approved"])
    assert e2.version == 2
    assert e2.value == "v1.1-approved"

    fact = orchestrator.read_blackboard("goal.spec")
    assert fact["goal.spec"].version == 2
    assert fact["goal.spec"].author_id == "agent-reviewer-01"


def test_check_health_and_failover() -> None:
    """Verify degraded node quarantine and edge recalculation."""
    orchestrator = SwarmTopologyOrchestrator()
    orchestrator.state.nodes["agent-worker-02"].status = SwarmNodeStatus.DEGRADED

    affected = orchestrator.check_health_and_failover()
    assert "agent-worker-02" in affected
    assert orchestrator.state.nodes["agent-worker-02"].connected_peers == []
