# ============================================================================
# Unit Tests for TreeStructuredSessionDagAndBranchSummaryCarrier (Item 147)
# Verifies lessons extraction from abandoned branches, carrier injection upon
# branch fork, and tree visualizer topology data export for Git DAG drawer.
# ============================================================================

import pytest

from myrm_agent_harness.agent.context_management.branching import (
    BranchCarrierForkRequest,
    BranchSummaryCarrierEngine,
    SessionDagGraph,
)


def test_extract_abandoned_branch_lessons() -> None:
    """Verifies distilling failures, constraints, and approaches from an abandoned branch."""
    graph = SessionDagGraph(session_id="dag-sess-test")
    engine = BranchSummaryCarrierEngine()

    # Step 1: Root message (Main branch)
    m1 = graph.add_message(role="user", content="Task: implement distributed cache locking")
    m2 = graph.add_message(role="assistant", content="Let's try Redis Redlock implementation")
    assert m1.node_id in graph.nodes

    # Step 2: Branch A attempts (Redis approach)
    b_redis = graph.branch_from_node(
        target_node_id=m2.node_id,
        new_content="Approach A: Connecting to Redis cluster at 10.0.0.1:6379",
        branch_id="branch-redis",
    )
    assert b_redis.node_id in graph.nodes
    graph.add_message(
        role="assistant",
        content="Executed script: connection timeout after 30s. Error: ConnectionRefusedError\nFailed to acquire lock",
        branch_id="branch-redis",
    )

    # Extract lessons from branch-redis
    summary = engine.extract_abandoned_branch_lessons(
        graph=graph,
        branch_id="branch-redis",
        custom_reason="Redis 集群网络隔离无法访问",
    )

    assert summary.branch_id == "branch-redis"
    assert "Redis 集群网络隔离无法访问" in summary.abandoned_reason
    assert any("Redis" in app for app in summary.attempted_approaches)
    assert any("ConnectionRefusedError" in err or "timeout" in err for err in summary.discovered_constraints)
    assert "<abandoned_branch_lessons" in summary.summary_markdown
    assert "</abandoned_branch_lessons>" in summary.summary_markdown


def test_fork_with_summary_carrier_injection() -> None:
    """Tests branching from historical fork point while carrying forward abandoned lessons."""
    graph = SessionDagGraph(session_id="dag-fork-test")
    engine = BranchSummaryCarrierEngine()

    # Create historical root and round 1
    m1 = graph.add_message(role="user", content="Database optimization task")
    m2 = graph.add_message(role="assistant", content="Planning DB index strategy")
    assert m1.node_id in graph.nodes

    # Branch 1 (failed approach)
    b1_lead = graph.branch_from_node(
        target_node_id=m2.node_id,
        new_content="Let's build global hash index on orders table",
        branch_id="branch-hash-index",
    )
    graph.add_message(
        role="assistant",
        content="Execution failed: memory limit exceeded. Error: OOM on /var/lib/mysql",
        branch_id="branch-hash-index",
    )

    # Fork new Branch 2 from m2 carrying lessons of branch-hash-index
    request = BranchCarrierForkRequest(
        source_branch_id="branch-hash-index",
        fork_point_node_id=m2.node_id,
        new_branch_name="BTree Partial Index Branch",
        new_prompt="Approach B: Create partial B-tree index on created_at",
        extract_lessons=True,
        custom_abandoned_reason="全表 Hash 索引内存超限 OOM",
    )

    response = engine.fork_with_summary_carrier(graph=graph, request=request)

    assert response.carrier_summary is not None
    assert response.fork_point_node_id == m2.node_id
    assert response.new_branch_id.startswith("branch-")

    # Verify new active node contains both carrier summary block and new prompt
    new_node = graph.nodes[response.new_active_node_id]
    assert "<abandoned_branch_lessons" in new_node.content
    assert "全表 Hash 索引内存超限 OOM" in new_node.content
    assert "Approach B: Create partial B-tree index on created_at" in new_node.content
    assert new_node.metadata.get("branch_name") == "BTree Partial Index Branch"

    # Verify origin failed branch nodes remain completely intact
    assert b1_lead.node_id in graph.nodes
    assert len(graph.nodes) >= 4


def test_export_tree_visualizer_view() -> None:
    """Tests generating tree topology views for the WebUI Git DAG branch drawer."""
    graph = SessionDagGraph(session_id="dag-tree-viz")
    engine = BranchSummaryCarrierEngine()

    m1 = graph.add_message(role="user", content="Root prompt")
    m2 = graph.add_message(role="assistant", content="Root response")

    # Create two branches
    b1 = graph.branch_from_node(target_node_id=m2.node_id, new_content="Branch 1 user message")
    assert b1.node_id in graph.nodes
    graph.add_message(role="assistant", content="Branch 1 assistant reply")

    b2 = graph.branch_from_node(target_node_id=m2.node_id, new_content="Branch 2 user message")

    views = engine.export_tree_visualizer_view(graph)
    assert len(views) == 5

    # Check root node: m1 has 3 direct children (m2, b1, b2)
    v_root = next(v for v in views if v.node_id == m1.node_id)
    assert v_root.parent_id is None
    assert v_root.children_count == 3
    assert not v_root.is_leaf

    # Check leaf node
    v_b2 = next(v for v in views if v.node_id == b2.node_id)
    assert v_b2.is_leaf
    assert v_b2.children_count == 0


def test_carrier_error_handling() -> None:
    """Verifies defensive error handling for non-existent fork points."""
    graph = SessionDagGraph(session_id="dag-err")
    engine = BranchSummaryCarrierEngine()

    request = BranchCarrierForkRequest(
        source_branch_id="missing-branch",
        fork_point_node_id="non-existent-node",
        new_branch_name="Branch X",
        new_prompt="Hello",
    )

    with pytest.raises(KeyError) as exc_info:
        engine.fork_with_summary_carrier(graph=graph, request=request)

    assert "non-existent-node" in str(exc_info.value)
