from __future__ import annotations

import pytest

from myrm_agent_harness.runtime.context import (
    BranchHistoricalTurn,
    RewindMode,
    SessionBranchingEngine,
)


def _make_turn(msg_id: str, content: str, role: str = "user") -> BranchHistoricalTurn:
    return BranchHistoricalTurn(
        message_id=msg_id,
        role=role,
        content=content,
        created_at_ms=1000,
    )


def test_session_registration_and_turn_append() -> None:
    """Test registering root session and appending conversation turns."""
    engine = SessionBranchingEngine()
    desc = engine.register_session(session_id="root_sess", branch_name="main")

    assert desc.session_id == "root_sess"
    assert desc.branch_name == "main"
    assert desc.parent_session_id is None

    engine.append_turn("root_sess", _make_turn("msg_1", "Hello"))
    engine.append_turn("root_sess", _make_turn("msg_2", "Hi there", role="assistant"))

    turns = engine.get_session_turns("root_sess")
    assert len(turns) == 2
    assert turns[0].message_id == "msg_1"
    assert turns[1].message_id == "msg_2"


def test_arbitrary_checkpoint_forking_and_isolation() -> None:
    """Test forking from message 3, verifying lineage and execution isolation."""
    engine = SessionBranchingEngine()
    engine.register_session("root_sess")

    for i in range(1, 6):
        engine.append_turn("root_sess", _make_turn(f"msg_{i}", f"Turn {i}"))

    # Fork at msg_3
    fork_res = engine.fork_session(
        parent_session_id="root_sess",
        fork_point_message_id="msg_3",
        branch_name="feature_experiment",
    )
    child_id = fork_res.new_session_id
    child_desc = fork_res.branch_descriptor

    assert child_desc.parent_session_id == "root_sess"
    assert child_desc.fork_point_message_id == "msg_3"
    assert child_desc.fork_point_turn_index == 3
    assert child_desc.branch_name == "feature_experiment"

    # Verify cloned turns strictly match prefix
    child_turns = engine.get_session_turns(child_id)
    assert [t.message_id for t in child_turns] == ["msg_1", "msg_2", "msg_3"]

    # Append to child and parent independently
    engine.append_turn(child_id, _make_turn("msg_child_only", "Exploring route B"))
    engine.append_turn("root_sess", _make_turn("msg_6", "Continuing main route"))

    # Confirm strict isolation
    assert len(engine.get_session_turns(child_id)) == 4
    assert len(engine.get_session_turns("root_sess")) == 6


def test_timeline_rewind_in_place_and_staging_modes() -> None:
    """Test both IN_PLACE_TRUNCATE and STAGING_BRANCH rewind strategies."""
    engine = SessionBranchingEngine()
    engine.register_session("sess_work")
    for i in range(1, 6):
        engine.append_turn("sess_work", _make_turn(f"msg_{i}", f"Content {i}"))

    # 1. IN_PLACE_TRUNCATE rewind to msg_3
    rewind_res = engine.rewind_session(
        session_id="sess_work",
        target_message_id="msg_3",
        mode=RewindMode.IN_PLACE_TRUNCATE,
    )
    assert rewind_res.mode == RewindMode.IN_PLACE_TRUNCATE
    assert [t.message_id for t in rewind_res.active_turns] == ["msg_1", "msg_2", "msg_3"]
    assert [t.message_id for t in rewind_res.truncated_turns] == ["msg_4", "msg_5"]
    assert len(engine.get_session_turns("sess_work")) == 3

    # 2. STAGING_BRANCH rewind to msg_2 (leaves sess_work intact, creates staging branch)
    staging_res = engine.rewind_session(
        session_id="sess_work",
        target_message_id="msg_2",
        mode=RewindMode.STAGING_BRANCH,
    )
    assert staging_res.mode == RewindMode.STAGING_BRANCH
    assert staging_res.created_staging_session_id is not None
    # Original remains untouched
    assert len(engine.get_session_turns("sess_work")) == 3
    # Staging branch has prefix up to msg_2
    staging_turns = engine.get_session_turns(staging_res.created_staging_session_id)
    assert [t.message_id for t in staging_turns] == ["msg_1", "msg_2"]


def test_lineage_tree_and_branch_navigator_view() -> None:
    """Test sibling discovery and BranchNavigatorView indexing (Branch 1/2, 2/2)."""
    engine = SessionBranchingEngine()
    engine.register_session("root_sess", branch_name="main")
    engine.append_turn("root_sess", _make_turn("msg_1", "Base idea"))

    # Create two sibling branches from root
    fork_1 = engine.fork_session("root_sess", "msg_1", branch_name="idea_A")
    fork_2 = engine.fork_session("root_sess", "msg_1", branch_name="idea_B")

    view_1 = engine.get_navigator_view(fork_1.new_session_id)
    assert view_1.current_branch_name == "idea_A"
    assert view_1.total_sibling_branches == 2
    assert view_1.current_sibling_index == 1
    assert view_1.parent_session_id == "root_sess"

    view_2 = engine.get_navigator_view(fork_2.new_session_id)
    assert view_2.current_branch_name == "idea_B"
    assert view_2.total_sibling_branches == 2
    assert view_2.current_sibling_index == 2

    root_view = engine.get_navigator_view("root_sess")
    assert len(root_view.children_branches) == 2
    assert root_view.children_branches[0].branch_name == "idea_A"
    assert root_view.children_branches[1].branch_name == "idea_B"


def test_edge_cases_and_error_handling() -> None:
    """Test exceptions for non-existent session or message lookups."""
    engine = SessionBranchingEngine()
    engine.register_session("sess_real")
    engine.append_turn("sess_real", _make_turn("msg_1", "Hi"))

    with pytest.raises(KeyError, match="Parent session 'unknown' not found"):
        engine.fork_session("unknown", "msg_1")

    with pytest.raises(ValueError, match="Fork point message 'invalid_msg' not found"):
        engine.fork_session("sess_real", "invalid_msg")

    with pytest.raises(ValueError, match="Target rewind message 'invalid_msg' not found"):
        engine.rewind_session("sess_real", "invalid_msg")
