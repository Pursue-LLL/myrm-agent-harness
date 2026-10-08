"""Unit tests for GraphMemoryReorganizationAndLineageTraceabilitySuite.

Tests multi-relational graph edge synthesis, white-box lineage DAG tracing, and version rollbacks.
"""

from myrm_agent_harness.toolkits.memory.graph_reorganization import (
    GraphMemoryReorganizationEngine,
    GraphRelationType,
    MemoryGraphNode,
    MemoryLineageTracker,
    MemoryNodeStatus,
    MultiRelationalDetector,
)


def test_lineage_tracker_registration_and_active_listing() -> None:
    """Test registering nodes and querying active vs superseded items."""
    tracker = MemoryLineageTracker()
    node1 = MemoryGraphNode(
        node_id="mem_coffee_v1",
        lineage_root_id="root_beverage_pref",
        version=1,
        subject="User",
        predicate="prefers_beverage",
        object_value="Black Coffee",
        content="User exclusively drinks hot black coffee in the morning.",
        status=MemoryNodeStatus.ACTIVE,
    )
    tracker.register_node(node1)

    active_nodes = tracker.list_active_nodes(subject="User")
    assert len(active_nodes) == 1
    assert active_nodes[0].node_id == "mem_coffee_v1"
    assert active_nodes[0].object_value == "Black Coffee"


def test_reorganizer_evolution_and_lineage_trail() -> None:
    """Test superseding node with atomic evolution and white-box trail verification."""
    tracker = MemoryLineageTracker()
    detector = MultiRelationalDetector()
    engine = GraphMemoryReorganizationEngine(tracker, detector)

    node1 = MemoryGraphNode(
        node_id="mem_coffee_v1",
        lineage_root_id="root_beverage_pref",
        version=1,
        subject="User",
        predicate="prefers_beverage",
        object_value="Black Coffee",
        content="User drinks black coffee.",
        status=MemoryNodeStatus.ACTIVE,
    )
    tracker.register_node(node1)

    node2 = MemoryGraphNode(
        node_id="mem_coffee_v2",
        lineage_root_id="",
        version=0,
        subject="User",
        predicate="prefers_beverage",
        object_value="Oat Latte",
        content="User switched to iced oat latte due to stomach sensitivity.",
    )

    old_n, new_n, edge = engine.record_evolution(
        superseded_node_id="mem_coffee_v1",
        new_node=node2,
        rationale="Switched preference to oat latte",
    )

    assert old_n.status == MemoryNodeStatus.SUPERSEDED
    assert new_n.status == MemoryNodeStatus.ACTIVE
    assert new_n.version == 2
    assert new_n.lineage_root_id == "root_beverage_pref"
    assert edge.relation_type == GraphRelationType.SUPERSEDES

    # Trace lineage trail of new node
    trail = tracker.trace_trail(new_n.node_id)
    assert trail.is_latest is True
    assert len(trail.ancestor_nodes) == 1
    assert trail.ancestor_nodes[0].node_id == "mem_coffee_v1"
    assert len(trail.steps) == 1
    assert trail.steps[0].relation_to_target == GraphRelationType.SUPERSEDES


def test_reorganizer_candidate_detection_and_batch_execution() -> None:
    """Test detecting subsumption and temporal relations across active nodes."""
    tracker = MemoryLineageTracker()
    detector = MultiRelationalDetector()
    engine = GraphMemoryReorganizationEngine(tracker, detector)

    # General concept
    node_parent = MemoryGraphNode(
        node_id="mem_tea_general",
        lineage_root_id="root_tea",
        version=1,
        subject="Tea",
        predicate="category",
        object_value="beverage",
        content="Tea drinks.",
        source_session_id="sess_001",
    )
    # Specific concept
    node_child = MemoryGraphNode(
        node_id="mem_tea_specific",
        lineage_root_id="root_jasmine",
        version=1,
        subject="Tea Jasmine",
        predicate="flavor",
        object_value="beverage jasmine fresh",
        content="Jasmine green tea with zero sugar added.",
        source_session_id="sess_001",
    )
    tracker.register_node(node_parent)
    tracker.register_node(node_child)

    report = engine.run_reorganization_batch(min_confidence=0.8)
    assert report.analyzed_nodes_count == 2
    assert report.created_edges_count >= 1
    assert len(report.edges) >= 1


def test_revert_to_version_rollback() -> None:
    """Test reversible history rolling back to historical node while preserving audit lineage."""
    tracker = MemoryLineageTracker()
    engine = GraphMemoryReorganizationEngine(tracker)

    node_v1 = MemoryGraphNode(
        node_id="mem_cfg_v1",
        lineage_root_id="root_cfg",
        version=1,
        subject="System",
        predicate="mode",
        object_value="Async",
        content="System runs in Async mode.",
    )
    tracker.register_node(node_v1)

    node_v2 = MemoryGraphNode(
        node_id="mem_cfg_v2",
        lineage_root_id="root_cfg",
        version=2,
        subject="System",
        predicate="mode",
        object_value="Sync",
        content="System temporarily forced to Sync mode.",
    )
    engine.record_evolution(
        superseded_node_id="mem_cfg_v1",
        new_node=node_v2,
        rationale="Switched to Sync mode for debugging",
    )

    # Now rollback to v1
    reverted_node, restored_v3 = tracker.revert_to_version(
        historical_node_id="mem_cfg_v1",
        new_node_id="mem_cfg_v3",
        rationale="Debugging completed, rolling back to Async",
    )

    assert reverted_node.node_id == "mem_cfg_v2"
    assert reverted_node.status == MemoryNodeStatus.REVERTED
    assert restored_v3.version == 3
    assert restored_v3.object_value == "Async"
    assert restored_v3.status == MemoryNodeStatus.ACTIVE

    # Verify audit trail of v3
    trail = tracker.trace_trail("mem_cfg_v3")
    assert len(trail.ancestor_nodes) >= 2
