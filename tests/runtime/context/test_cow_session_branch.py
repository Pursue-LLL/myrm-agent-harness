"""Tests for Instant Session Forking and Copy-on-Write State Branching Engine."""

from __future__ import annotations

import pytest

from myrm_agent_harness.runtime.context.cow_session_branch import (
    BranchMessageEntry,
    CoWSessionBranchManager,
)


def _make_msg(turn_id: str, content: str, role: str = "user") -> BranchMessageEntry:
    return BranchMessageEntry(
        turn_id=turn_id,
        role=role,
        content=content,
        timestamp=1000.0,
    )


def test_root_session_creation_and_append():
    manager = CoWSessionBranchManager()
    init_msgs = [
        _make_msg("t-1", "Hello"),
        _make_msg("t-2", "Hi there", role="assistant"),
    ]
    root_desc = manager.create_root_session("root-sess", initial_messages=init_msgs, branch_label="main")

    assert root_desc.session_id == "root-sess"
    assert root_desc.parent_session_id is None
    assert root_desc.fork_point_turn_id is None
    assert root_desc.depth == 0
    assert root_desc.branch_label == "main"

    manager.append_message("root-sess", _make_msg("t-3", "How are you?"))

    view = manager.get_projected_view("root-sess")
    assert view.session_id == "root-sess"
    assert view.inherited_turns_count == 0
    assert view.local_turns_count == 3
    assert view.total_turns_count == 3
    assert [m.turn_id for m in view.messages] == ["t-1", "t-2", "t-3"]


def test_instant_fork_and_projected_view_isolation():
    manager = CoWSessionBranchManager()
    manager.create_root_session(
        "root-sess",
        initial_messages=[
            _make_msg("t-1", "Turn 1"),
            _make_msg("t-2", "Turn 2"),
            _make_msg("t-3", "Turn 3"),
        ],
    )

    # Fork at t-2
    branch_desc = manager.fork_session(
        parent_session_id="root-sess",
        fork_point_turn_id="t-2",
        new_session_id="branch-exp-a",
        branch_label="experiment-a",
    )

    assert branch_desc.session_id == "branch-exp-a"
    assert branch_desc.parent_session_id == "root-sess"
    assert branch_desc.fork_point_turn_id == "t-2"
    assert branch_desc.depth == 1

    # Verify initial projected view before local messages
    view_a = manager.get_projected_view("branch-exp-a")
    assert view_a.inherited_turns_count == 2
    assert view_a.local_turns_count == 0
    assert view_a.total_turns_count == 2
    assert [m.turn_id for m in view_a.messages] == ["t-1", "t-2"]

    # Append to branch-exp-a
    manager.append_message("branch-exp-a", _make_msg("t-a-1", "Alternative path"))

    # Also append to root-sess
    manager.append_message("root-sess", _make_msg("t-4", "Root continue"))

    view_a_after = manager.get_projected_view("branch-exp-a")
    assert view_a_after.inherited_turns_count == 2
    assert view_a_after.local_turns_count == 1
    assert view_a_after.total_turns_count == 3
    assert [m.turn_id for m in view_a_after.messages] == ["t-1", "t-2", "t-a-1"]

    # Root session must remain isolated and unaffected
    view_root = manager.get_projected_view("root-sess")
    assert view_root.total_turns_count == 4
    assert [m.turn_id for m in view_root.messages] == ["t-1", "t-2", "t-3", "t-4"]


def test_multi_tier_cascading_forking():
    manager = CoWSessionBranchManager()
    manager.create_root_session(
        "root",
        initial_messages=[
            _make_msg("r-1", "Root Msg 1"),
            _make_msg("r-2", "Root Msg 2"),
        ],
    )

    # Level 1 Fork at r-1
    manager.fork_session("root", "r-1", "branch-l1", "Level 1")
    manager.append_message("branch-l1", _make_msg("l1-1", "L1 Msg 1"))
    manager.append_message("branch-l1", _make_msg("l1-2", "L1 Msg 2"))

    # Level 2 Fork from branch-l1 at l1-1
    manager.fork_session("branch-l1", "l1-1", "branch-l2", "Level 2")
    manager.append_message("branch-l2", _make_msg("l2-1", "L2 Msg 1"))

    view_l2 = manager.get_projected_view("branch-l2")
    assert view_l2.lineage_path == ("root", "branch-l1", "branch-l2")
    assert [m.turn_id for m in view_l2.messages] == ["r-1", "l1-1", "l2-1"]
    assert view_l2.inherited_turns_count == 2
    assert view_l2.local_turns_count == 1
    assert view_l2.total_turns_count == 3


def test_cow_artifact_overrides_and_inheritance():
    manager = CoWSessionBranchManager()
    manager.create_root_session("root", initial_messages=[_make_msg("m-1", "Start")])

    # Root creates artifact
    rec1 = manager.upsert_artifact("root", "spec.md", "# Root Spec")
    assert rec1.version == 1
    assert rec1.origin_session_id == "root"

    # Fork branch
    manager.fork_session("root", "m-1", "branch-doc", "doc-branch")

    # Before override, view inherits root artifact
    view_initial = manager.get_projected_view("branch-doc")
    assert "spec.md" in view_initial.artifacts
    assert view_initial.artifacts["spec.md"].version == 1
    assert view_initial.artifacts["spec.md"].content == "# Root Spec"

    # Branch overrides artifact
    rec2 = manager.upsert_artifact("branch-doc", "spec.md", "# Overridden Spec")
    assert rec2.version == 2
    assert rec2.origin_session_id == "branch-doc"

    # Branch view shows overridden artifact
    view_updated = manager.get_projected_view("branch-doc")
    assert view_updated.artifacts["spec.md"].version == 2
    assert view_updated.artifacts["spec.md"].content == "# Overridden Spec"

    # Root remains isolated at version 1
    root_view = manager.get_projected_view("root")
    assert root_view.artifacts["spec.md"].version == 1
    assert root_view.artifacts["spec.md"].content == "# Root Spec"


def test_branch_hierarchy_tree_and_child_listing():
    manager = CoWSessionBranchManager()
    manager.create_root_session("root", initial_messages=[_make_msg("m-1", "Hi")])
    manager.fork_session("root", "m-1", "b1", "Branch 1")
    manager.fork_session("root", "m-1", "b2", "Branch 2")
    manager.append_message("b1", _make_msg("b1-1", "Sub msg"))
    manager.fork_session("b1", "b1-1", "b1-sub", "B1 Sub")

    children = manager.list_child_branches("root")
    assert [c.session_id for c in children] == ["b1", "b2"]

    tree = manager.get_branch_hierarchy_tree("root")
    assert tree["session_id"] == "root"
    assert len(tree["children"]) == 2  # type: ignore
    b1_node = next(c for c in tree["children"] if c["session_id"] == "b1")  # type: ignore
    assert len(b1_node["children"]) == 1
    assert b1_node["children"][0]["session_id"] == "b1-sub"


def test_fork_validation_and_error_handling():
    manager = CoWSessionBranchManager()
    manager.create_root_session("root", initial_messages=[_make_msg("m-1", "Start")])

    # 1. Non-existent parent
    with pytest.raises(KeyError, match="Parent session 'ghost' does not exist"):
        manager.fork_session("ghost", "m-1", "child")

    # 2. Duplicate session_id
    with pytest.raises(ValueError, match="Session 'root' already exists"):
        manager.fork_session("root", "m-1", "root")

    # 3. Invalid turn_id
    with pytest.raises(ValueError, match="Fork point turn 'invalid-turn' not found"):
        manager.fork_session("root", "invalid-turn", "child")
