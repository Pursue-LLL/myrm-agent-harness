# ============================================================================
# Unit Tests for DualBranchingSessionDagAndEditFromHereEngine (Item 144)
# Verifies in-session branching, standalone forks, UI navigator metadata,
# path reconstruction, and serialization lossless fidelity.
# ============================================================================

import pytest

from myrm_agent_harness.agent.context_management.branching import (
    BranchForkMode,
    SessionDagGraph,
    SessionDagNode,
)


def test_linear_session_dag_construction() -> None:
    """Verifies sequential appending without branches forms a straight linear path."""
    graph = SessionDagGraph(session_id="test-sess-1")
    assert graph.session_id == "test-sess-1"
    assert graph.active_leaf_id is None

    m1 = graph.add_message(role="system", content="You are a helpful assistant.")
    assert len(graph.root_node_ids) == 1
    assert graph.root_node_ids[0] == m1.node_id
    assert graph.active_leaf_id == m1.node_id

    m2 = graph.add_message(role="user", content="Write a python quicksort.")
    assert m2.parent_id == m1.node_id
    assert m1.children_ids == [m2.node_id]

    m3 = graph.add_message(role="assistant", content="Here is quicksort code...")
    assert m3.parent_id == m2.node_id

    linear = graph.get_linear_path()
    assert len(linear) == 3
    assert [n.role for n in linear] == ["system", "user", "assistant"]
    assert [n.node_id for n in linear] == [m1.node_id, m2.node_id, m3.node_id]


def test_edit_from_here_in_session_branching() -> None:
    """Tests 'Edit from here' branching from an earlier user message."""
    graph = SessionDagGraph(session_id="test-branch-sess")

    # Round 1
    m1 = graph.add_message(role="user", content="Option A prompt")
    m2 = graph.add_message(role="assistant", content="Option A reply")

    # Round 2 - Edit from here: branch from m1 with alternative prompt
    b1 = graph.branch_from_node(target_node_id=m1.node_id, new_content="Option B prompt (edited)")
    assert b1.parent_id == m1.parent_id  # Both are roots in this case
    assert b1.branch_id.startswith("branch-")

    # Verify navigator meta for m1 and b1
    meta1 = graph.get_navigator_meta(m1.node_id)
    assert meta1 is not None
    assert meta1.branch_index == 1
    assert meta1.total_branches == 2

    meta_b1 = graph.get_navigator_meta(b1.node_id)
    assert meta_b1 is not None
    assert meta_b1.branch_index == 2
    assert meta_b1.total_branches == 2

    # Append response to branch B
    b2 = graph.add_message(role="assistant", content="Option B reply")
    assert b2.parent_id == b1.node_id

    # Active path is currently on Branch B
    path_b = graph.get_linear_path()
    assert [n.node_id for n in path_b] == [b1.node_id, b2.node_id]

    # Switch back to Branch A
    path_a = graph.switch_active_branch(m2.node_id)
    assert [n.node_id for n in path_a] == [m1.node_id, m2.node_id]
    assert graph.active_leaf_id == m2.node_id


def test_fork_standalone_session_isolation() -> None:
    """Tests 'New session' independent clone from a historical fork node."""
    graph = SessionDagGraph(session_id="origin-sess")
    m1 = graph.add_message(role="user", content="Step 1: Planning")
    m2 = graph.add_message(role="assistant", content="Step 1: Plan confirmed")
    m3 = graph.add_message(role="user", content="Step 2: Execution branch A")
    m4 = graph.add_message(role="assistant", content="Step 2: Executed A")

    # Fork standalone session from m2
    forked_graph, fork_result = graph.fork_standalone_session(
        fork_point_node_id=m2.node_id,
        new_session_id="cloned-standalone-sess",
    )

    assert fork_result.new_session_id == "cloned-standalone-sess"
    assert fork_result.origin_session_id == "origin-sess"
    assert fork_result.copied_nodes_count == 2
    assert fork_result.active_leaf_node_id == m2.node_id

    # Check cloned linear history
    cloned_path = forked_graph.get_linear_path()
    assert len(cloned_path) == 2
    assert [n.node_id for n in cloned_path] == [m1.node_id, m2.node_id]

    # Mutation test: append in forked session does not affect origin
    fork_m3 = forked_graph.add_message(role="user", content="Step 2: Execution branch Independent")
    assert fork_m3.node_id not in graph.nodes
    assert len(forked_graph.nodes) == 3
    assert len(graph.nodes) == 4

    # Verify origin path unchanged
    origin_path = graph.get_linear_path()
    assert len(origin_path) == 4
    assert [n.node_id for n in origin_path] == [m1.node_id, m2.node_id, m3.node_id, m4.node_id]


def test_session_dag_serialization_roundtrip() -> None:
    """Verifies to_dict and from_dict preserve entire DAG topology, nodes, and active pointer."""
    graph = SessionDagGraph(session_id="sess-serialize-test")
    m1 = graph.add_message(role="system", content="Sys prompt")
    m2 = graph.add_message(role="user", content="User prompt 1", metadata={"tokens": 15})
    b1 = graph.branch_from_node(target_node_id=m2.node_id, new_content="User prompt 1 variant")

    payload = graph.to_dict()
    assert payload["session_id"] == "sess-serialize-test"
    assert payload["active_leaf_id"] == b1.node_id

    restored = SessionDagGraph.from_dict(payload)
    assert restored.session_id == "sess-serialize-test"
    assert restored.active_leaf_id == b1.node_id
    assert m1.node_id in restored.nodes
    assert len(restored.nodes) == len(graph.nodes)
    assert restored.nodes[m2.node_id].metadata == {"tokens": 15}

    # Verify topology retained in restored instance
    meta_m2 = restored.get_navigator_meta(m2.node_id)
    assert meta_m2 is not None
    assert meta_m2.total_branches == 2


def test_edge_cases_and_error_handling() -> None:
    """Tests invalid node lookups and boundary empty states."""
    graph = SessionDagGraph(session_id="empty-sess")
    assert graph.get_linear_path() == []
    assert graph.get_navigator_meta("non-existent") is None

    with pytest.raises(KeyError):
        graph.branch_from_node("missing-node", "content")

    with pytest.raises(KeyError):
        graph.fork_standalone_session("missing-node")

    with pytest.raises(KeyError):
        graph.switch_active_branch("missing-node")

    # Node serialization
    node = SessionDagNode(
        node_id="n1",
        parent_id=None,
        children_ids=["n2"],
        branch_id="test",
        role="user",
        content="hello",
        metadata={"flag": True, "count": 42},
    )
    ndict = node.to_dict()
    restored_node = SessionDagNode.from_dict(ndict)
    assert restored_node.node_id == "n1"
    assert restored_node.metadata["count"] == 42
    assert BranchForkMode.IN_SESSION_BRANCH == "in_session_branch"
