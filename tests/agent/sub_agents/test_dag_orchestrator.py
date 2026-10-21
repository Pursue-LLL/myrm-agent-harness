"""Unit tests for DAG Visual Orchestrator with Cold Resume and Bidirectional Feedback."""

import pytest
from myrm_agent_harness.agent.sub_agents.dag_orchestrator import (
    CyclicDependencyError,
    DagColdResumeEngine,
    DagDependencyPlanner,
    DagNode,
    DagNodeStatus,
    DagRole,
    NodeNotFoundError,
)


@pytest.fixture
def planner() -> DagDependencyPlanner:
    return DagDependencyPlanner()


@pytest.fixture
def engine(planner: DagDependencyPlanner) -> DagColdResumeEngine:
    return DagColdResumeEngine(planner=planner)


def test_plan_team_dag_decomposition(planner: DagDependencyPlanner) -> None:
    plan = planner.plan_team_dag("Build distributed key-value store with Raft consensus")
    assert plan.dag_id.startswith("dag-")
    assert len(plan.nodes) == 6

    # Verify roles
    roles = [node.role for node in plan.nodes.values()]
    assert DagRole.ANALYST in roles
    assert DagRole.ARCHITECT in roles
    assert DagRole.CODER in roles
    assert DagRole.TESTER in roles
    assert DagRole.RELEASE_MANAGER in roles

    # Verify initial ready node is analyst only
    assert plan.ready_node_ids == ["node-analyst"]


def test_validate_cycle_free_topological_sort(planner: DagDependencyPlanner) -> None:
    plan = planner.plan_team_dag("Implement OAuth2 Server")
    order = plan.topological_order
    assert len(order) == 6
    assert order.index("node-analyst") < order.index("node-architect")
    assert order.index("node-architect") < order.index("node-coder-core")
    assert order.index("node-architect") < order.index("node-coder-aux")
    assert order.index("node-coder-core") < order.index("node-tester")
    assert order.index("node-coder-aux") < order.index("node-tester")
    assert order.index("node-tester") < order.index("node-release")


def test_cyclic_dependency_detection(planner: DagDependencyPlanner) -> None:
    # Construct nodes with an intentional cycle
    cyclic_nodes = {
        "A": DagNode(node_id="A", role=DagRole.ANALYST, title="A", instruction="A", depends_on=["C"]),
        "B": DagNode(node_id="B", role=DagRole.ARCHITECT, title="B", instruction="B", depends_on=["A"]),
        "C": DagNode(node_id="C", role=DagRole.CODER, title="C", instruction="C", depends_on=["B"]),
    }
    with pytest.raises(CyclicDependencyError, match="Cyclic dependency detected"):
        planner.validate_cycle_free(cyclic_nodes)


def test_ready_nodes_parallel_advancement(
    planner: DagDependencyPlanner, engine: DagColdResumeEngine
) -> None:
    plan = planner.plan_team_dag("Refactor Cache")
    nodes = plan.nodes

    # 1. Analyst is ready
    ready = planner.get_ready_nodes(nodes)
    assert ready == ["node-analyst"]

    # 2. Complete Analyst
    engine.execute_node_step(nodes, "node-analyst")
    ready = planner.get_ready_nodes(nodes)
    assert ready == ["node-architect"]

    # 3. Complete Architect -> both core and aux coders become ready in parallel!
    engine.execute_node_step(nodes, "node-architect")
    ready = planner.get_ready_nodes(nodes)
    assert sorted(ready) == ["node-coder-aux", "node-coder-core"]

    # 4. Complete only core coder -> tester is NOT ready yet because aux coder is pending
    engine.execute_node_step(nodes, "node-coder-core")
    ready = planner.get_ready_nodes(nodes)
    assert ready == ["node-coder-aux"]

    # 5. Complete aux coder -> tester is now ready
    engine.execute_node_step(nodes, "node-coder-aux")
    ready = planner.get_ready_nodes(nodes)
    assert ready == ["node-tester"]


def test_checkpoint_persistence_and_cold_resume(
    planner: DagDependencyPlanner, engine: DagColdResumeEngine
) -> None:
    plan = planner.plan_team_dag("Implement Token Bucket Rate Limiter")
    dag_id = plan.dag_id
    nodes = plan.nodes

    # Execute Analyst and Architect
    engine.execute_node_step(nodes, "node-analyst")
    engine.execute_node_step(nodes, "node-architect")

    # Save checkpoint
    snapshot = engine.save_checkpoint(dag_id, nodes)
    assert snapshot.dag_id == dag_id
    assert sorted(snapshot.completed_node_ids) == ["node-analyst", "node-architect"]

    # Simulate sandbox crash & restart: restore via cold_resume
    restored_nodes, ready_ids = engine.cold_resume(dag_id)
    assert restored_nodes["node-analyst"].status == DagNodeStatus.COMPLETED
    assert restored_nodes["node-architect"].status == DagNodeStatus.COMPLETED
    # Nodes were NOT re-executed; coders are ready immediately
    assert sorted(ready_ids) == ["node-coder-aux", "node-coder-core"]


def test_bidirectional_rejection_and_cascade_loopback(
    planner: DagDependencyPlanner, engine: DagColdResumeEngine
) -> None:
    plan = planner.plan_team_dag("High Performance Parser")
    nodes = plan.nodes

    # Advance through analyst, architect, both coders, and tester
    engine.execute_node_step(nodes, "node-analyst")
    engine.execute_node_step(nodes, "node-architect")
    engine.execute_node_step(nodes, "node-coder-core")
    engine.execute_node_step(nodes, "node-coder-aux")
    engine.execute_node_step(nodes, "node-tester")

    assert nodes["node-coder-core"].status == DagNodeStatus.COMPLETED
    assert nodes["node-tester"].status == DagNodeStatus.COMPLETED

    # Tester rejects architect contract due to concurrency data race!
    feedback = "Data race detected in atomic pointer swap. Redesign mutex boundary."
    affected = engine.reject_and_loopback(nodes, "node-architect", feedback)

    # Architect is marked REJECTED_LOOPBACK with feedback
    assert nodes["node-architect"].status == DagNodeStatus.REJECTED_LOOPBACK
    assert nodes["node-architect"].rejection_feedback == feedback

    # All downstream nodes (both coders and tester) are cascaded back to PENDING!
    assert nodes["node-coder-core"].status == DagNodeStatus.PENDING
    assert nodes["node-coder-aux"].status == DagNodeStatus.PENDING
    assert nodes["node-tester"].status == DagNodeStatus.PENDING
    assert "node-coder-core" in affected
    assert "node-tester" in affected

    # Only architect is now ready for revision
    ready = planner.get_ready_nodes(nodes)
    assert ready == ["node-architect"]


def test_node_not_found_errors(engine: DagColdResumeEngine) -> None:
    nodes: dict[str, DagNode] = {}
    with pytest.raises(NodeNotFoundError):
        engine.execute_node_step(nodes, "nonexistent")

    with pytest.raises(NodeNotFoundError):
        engine.reject_and_loopback(nodes, "nonexistent", "bad")
