# ============================================================================
# Unit Tests: In-Place Message Tree Branching & Version Navigator (Item 164)
# ============================================================================

import pytest

from myrm_agent_harness.agent.context_management.message_tree import (
    InPlaceMessageTreeEngine,
    TreeNodeRole,
)


def test_linear_append_and_active_timeline() -> None:
    """Test sequential message appending and active linear path resolution."""
    engine = InPlaceMessageTreeEngine()
    session_id = "session-test-linear"

    n1 = engine.append_message(session_id, TreeNodeRole.SYSTEM, "You are helpful.")
    n2 = engine.append_message(session_id, TreeNodeRole.USER, "Hello AI")
    n3 = engine.append_message(session_id, TreeNodeRole.ASSISTANT, "Hello Human")

    assert n1.parent_id is None
    assert n2.parent_id == n1.node_id
    assert n3.parent_id == n2.node_id

    assert n1.sibling_index == 1
    assert n1.total_siblings == 1
    assert n3.sibling_index == 1
    assert n3.total_siblings == 1

    timeline = engine.get_active_timeline_messages(session_id)
    assert len(timeline) == 3
    assert [m.node_id for m in timeline] == [n1.node_id, n2.node_id, n3.node_id]


def test_branch_alternative_and_sibling_sync() -> None:
    """Test branching alternative variants under the same parent and sibling count sync."""
    engine = InPlaceMessageTreeEngine()
    session_id = "session-test-branch"

    n1 = engine.append_message(session_id, TreeNodeRole.USER, "Tell me a joke")
    # First response candidate
    n2_v1 = engine.append_message(session_id, TreeNodeRole.ASSISTANT, "Why did the chicken cross?")
    assert n2_v1.sibling_index == 1
    assert n2_v1.total_siblings == 1

    # Branch second candidate (< 2/2 >)
    n2_v2 = engine.branch_alternative(
        session_id=session_id,
        sibling_node_id=n2_v1.node_id,
        role=TreeNodeRole.ASSISTANT,
        content="Knock knock!",
    )
    assert n2_v2.parent_id == n1.node_id
    assert n2_v2.sibling_index == 2
    assert n2_v2.total_siblings == 2

    # Branch third candidate (< 3/3 >)
    n2_v3 = engine.branch_alternative(
        session_id=session_id,
        sibling_node_id=n2_v1.node_id,
        role=TreeNodeRole.ASSISTANT,
        content="I have no jokes today.",
    )
    assert n2_v3.sibling_index == 3
    assert n2_v3.total_siblings == 3

    # Newly branched candidate is automatically active
    timeline = engine.get_active_timeline_messages(session_id)
    assert len(timeline) == 2
    assert timeline[0].node_id == n1.node_id
    assert timeline[1].node_id == n2_v3.node_id

    # Sibling versions summary check
    versions = engine.get_sibling_versions(session_id, n2_v1.node_id)
    assert len(versions) == 3
    assert [v.sibling_index for v in versions] == [1, 2, 3]
    assert versions[0].is_active is False
    assert versions[1].is_active is False
    assert versions[2].is_active is True


def test_switch_sibling_version_navigation() -> None:
    """Test in-place switching of sibling versions (< 1/3 >) and child subtrees."""
    engine = InPlaceMessageTreeEngine()
    session_id = "session-test-switch"

    u1 = engine.append_message(session_id, TreeNodeRole.USER, "Write python code")
    a1_v1 = engine.append_message(session_id, TreeNodeRole.ASSISTANT, "def foo(): pass")
    # User continues on v1
    u2_on_v1 = engine.append_message(session_id, TreeNodeRole.USER, "Now add docstring")

    # Now branch alternative on a1 (< 2/2 >)
    a1_v2 = engine.branch_alternative(
        session_id=session_id,
        sibling_node_id=a1_v1.node_id,
        role=TreeNodeRole.ASSISTANT,
        content="def foo() -> None: ...",
    )
    # Active timeline now ends at a1_v2 because it was just branched
    active_now = engine.get_active_timeline_messages(session_id)
    assert [m.node_id for m in active_now] == [u1.node_id, a1_v2.node_id]

    # Switch back to version 1 (< 1/2 >)
    switch_res = engine.switch_sibling_version(session_id, a1_v2.node_id, target_sibling_index=1)
    assert switch_res.target_node_id == a1_v1.node_id
    assert switch_res.new_sibling_index == 1
    assert switch_res.total_siblings == 2

    # Active timeline now follows v1 and its child u2_on_v1!
    active_switched = engine.get_active_timeline_messages(session_id)
    assert [m.node_id for m in active_switched] == [u1.node_id, a1_v1.node_id, u2_on_v1.node_id]


def test_message_tree_graph_and_errors() -> None:
    """Test full DAG graph export and error handling boundaries."""
    engine = InPlaceMessageTreeEngine()
    session_id = "session-test-graph"

    # Empty session graph
    empty_graph = engine.get_message_tree_graph(session_id)
    assert empty_graph.root_node_id is None
    assert len(empty_graph.nodes) == 0

    root = engine.append_message(session_id, TreeNodeRole.USER, "Root message")
    child = engine.append_message(session_id, TreeNodeRole.ASSISTANT, "Child message")

    graph = engine.get_message_tree_graph(session_id)
    assert graph.root_node_id == root.node_id
    assert graph.active_leaf_id == child.node_id
    assert graph.active_path_ids == (root.node_id, child.node_id)
    assert len(graph.nodes) == 2

    # Errors: invalid index
    with pytest.raises(IndexError):
        engine.switch_sibling_version(session_id, child.node_id, target_sibling_index=99)

    with pytest.raises(IndexError):
        engine.switch_sibling_version(session_id, child.node_id, target_sibling_index=0)

    # Errors: unknown node
    with pytest.raises(KeyError):
        engine.branch_alternative(session_id, "unknown-node", TreeNodeRole.ASSISTANT, "bad")

    with pytest.raises(KeyError):
        engine.get_sibling_versions(session_id, "unknown-node")
