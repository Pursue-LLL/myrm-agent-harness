"""Unit tests for Pi Harness v2 Deterministic Subagent Session Fork Primitive (Item 51)."""

import pytest

from myrm_agent_harness.agent.sub_agents.session_fork import (
    DeterministicSessionForkManager,
    ForkConflictError,
    ForkedSessionNode,
    ForkScope,
)


def test_deterministic_child_session_id_derivation() -> None:
    parent_id = "parent-sess-001"
    tool_call_1 = "call-llm-123"
    tool_call_2 = "call-llm-456"

    # Deterministic generation: same inputs produce exact same output
    id1_a = DeterministicSessionForkManager.derive_child_session_id(parent_id, tool_call_1)
    id1_b = DeterministicSessionForkManager.derive_child_session_id(parent_id, tool_call_1)
    assert id1_a == id1_b
    assert id1_a.startswith("child-")

    # Distinct inputs produce distinct IDs
    id2 = DeterministicSessionForkManager.derive_child_session_id(parent_id, tool_call_2)
    assert id1_a != id2


def test_safe_replay_reattach_prevents_twins() -> None:
    manager = DeterministicSessionForkManager()
    parent_id = "parent-sess-002"
    tool_call_id = "call-investigate-01"

    # 1st execution: fresh fork
    res1 = manager.fork_child_session(
        parent_session_id=parent_id,
        tool_call_id=tool_call_id,
        scope=ForkScope.BRANCH,
    )
    assert res1.is_reattached is False
    assert res1.copied_nodes_count == 1  # synthetic root
    child_id = res1.child_session_id

    # Verify link state
    link = manager.get_child_session(child_id)
    assert link is not None
    assert link.reattach_count == 0

    # 2nd execution (e.g. replay after crash or retry): safe reattach
    res2 = manager.fork_child_session(
        parent_session_id=parent_id,
        tool_call_id=tool_call_id,
        scope=ForkScope.BRANCH,
    )
    assert res2.is_reattached is True
    assert res2.child_session_id == child_id
    assert link.reattach_count == 1

    # 3rd execution: further reattach increments count without creating duplicate twin
    res3 = manager.fork_child_session(
        parent_session_id=parent_id,
        tool_call_id=tool_call_id,
        scope=ForkScope.BRANCH,
    )
    assert res3.is_reattached is True
    assert link.reattach_count == 2

    # Only 1 child exists under parent
    children = manager.list_children_for_parent(parent_id)
    assert len(children) == 1
    assert children[0].child_session_id == child_id


def test_branch_scope_copies_only_active_lineage() -> None:
    manager = DeterministicSessionForkManager()
    parent_id = "parent-sess-003"
    tool_call_id = "call-branch-test"

    # Construct parent tree:
    # root -> node-a -> node-b
    # root -> node-c (side branch)
    nodes = [
        ForkedSessionNode("root", None, "root", "Root message"),
        ForkedSessionNode("node-a", "root", "message", "Step A"),
        ForkedSessionNode("node-b", "node-a", "tool_result", "Step B Result"),
        ForkedSessionNode("node-c", "root", "message", "Side branch Step C"),
    ]

    res = manager.fork_child_session(
        parent_session_id=parent_id,
        tool_call_id=tool_call_id,
        scope=ForkScope.BRANCH,
        parent_nodes=nodes,
        target_leaf_id="node-b",
    )

    assert res.is_reattached is False
    assert res.copied_nodes_count == 3  # root, node-a, node-b only (excluding node-c)

    child_nodes = manager.get_child_nodes(res.child_session_id)
    node_ids = [n.node_id for n in child_nodes]
    assert node_ids == ["root", "node-a", "node-b"]
    assert "node-c" not in node_ids


def test_tree_scope_copies_full_topology() -> None:
    manager = DeterministicSessionForkManager()
    parent_id = "parent-sess-004"
    tool_call_id = "call-tree-test"

    nodes = [
        ForkedSessionNode("root", None, "root", "Root message"),
        ForkedSessionNode("node-a", "root", "message", "Step A"),
        ForkedSessionNode("node-b", "node-a", "tool_result", "Step B Result"),
        ForkedSessionNode("node-c", "root", "message", "Side branch Step C"),
    ]

    res = manager.fork_child_session(
        parent_session_id=parent_id,
        tool_call_id=tool_call_id,
        scope=ForkScope.TREE,
        parent_nodes=nodes,
    )

    assert res.is_reattached is False
    assert res.copied_nodes_count == 4

    child_nodes = manager.get_child_nodes(res.child_session_id)
    node_ids = [n.node_id for n in child_nodes]
    assert node_ids == ["root", "node-a", "node-b", "node-c"]


def test_conflict_error_on_mismatched_invocation(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = DeterministicSessionForkManager()
    parent_1 = "parent-alpha"
    parent_2 = "parent-beta"
    tool_call = "shared-call-id"

    # Force identical derived child ID to test collision guard
    fixed_id = "child-fixed-collision"
    monkeypatch.setattr(
        manager,
        "derive_child_session_id",
        lambda p, t: fixed_id,
    )

    # First fork succeeds
    res1 = manager.fork_child_session(parent_1, tool_call)
    assert res1.child_session_id == fixed_id

    # Second fork with different parent must raise ForkConflictError
    with pytest.raises(ForkConflictError):
        manager.fork_child_session(parent_2, tool_call)


def test_list_children_and_reset() -> None:
    manager = DeterministicSessionForkManager()
    parent_id = "parent-multi-children"

    res_a = manager.fork_child_session(parent_id, "call-1")
    res_b = manager.fork_child_session(parent_id, "call-2")

    children = manager.list_children_for_parent(parent_id)
    assert len(children) == 2
    child_ids = {c.child_session_id for c in children}
    assert res_a.child_session_id in child_ids
    assert res_b.child_session_id in child_ids

    manager.reset()
    assert len(manager.list_children_for_parent(parent_id)) == 0
