"""Unit tests for Dual-Branching Session Fork and In-Place Turn Rewind Engine.

Validates tree-structured DAG conversation tracking, "New Session From Here" deep cloning,
"Edit From Here" non-destructive version branching, and active timeline projection.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management.dual_branching import (
    DualBranchingSessionEngine,
)


def test_linear_conversation_append_and_projected_timeline() -> None:
    """Verifies sequential message append and projected linear timeline retrieval."""
    engine = DualBranchingSessionEngine()
    session_id = "session-linear-01"

    m1 = engine.append_message(session_id, role="system", content="You are a coding assistant.")
    m2 = engine.append_message(session_id, role="user", content="Explain Dijkstra algorithm.")
    m3 = engine.append_message(session_id, role="assistant", content="Dijkstra finds shortest paths.")

    timeline = engine.get_active_projected_timeline(session_id)
    assert len(timeline) == 3
    assert [m.message_id for m in timeline] == [m1.message_id, m2.message_id, m3.message_id]
    assert timeline[1].parent_id == m1.message_id
    assert timeline[2].parent_id == m2.message_id


def test_posture_one_new_session_from_here_cloning() -> None:
    """Verifies Posture 1: Fork an independent session from an earlier turn without polluting source."""
    engine = DualBranchingSessionEngine()
    src_session = "session-source-100"
    new_session = "session-cloned-200"

    # Build 5-turn conversation in source
    m1 = engine.append_message(src_session, role="system", content="System Prompt Root")
    m2 = engine.append_message(src_session, role="user", content="Step 1: Parse AST")
    m3 = engine.append_message(src_session, role="assistant", content="AST Parsed successfully")
    m4 = engine.append_message(src_session, role="user", content="Step 2: Generate Bytecode")
    m5 = engine.append_message(src_session, role="assistant", content="Bytecode Generated")

    # Clone new session from Step 1 assistant response (m3)
    fork_res = engine.new_session_from_here(
        source_session_id=src_session,
        cutoff_message_id=m3.message_id,
        new_session_id=new_session,
    )

    assert fork_res.source_session_id == src_session
    assert fork_res.new_session_id == new_session
    assert fork_res.cloned_message_count == 3

    # Cloned session should only have messages up to m3
    cloned_timeline = engine.get_active_projected_timeline(new_session)
    assert len(cloned_timeline) == 3
    assert [m.content for m in cloned_timeline] == [
        "System Prompt Root",
        "Step 1: Parse AST",
        "AST Parsed successfully",
    ]

    # Source session remains intact with all 5 messages
    src_timeline = engine.get_active_projected_timeline(src_session)
    assert len(src_timeline) == 5
    assert src_timeline[-1].message_id == m5.message_id


def test_posture_two_in_place_edit_from_here_and_version_shuttle() -> None:
    """Verifies Posture 2: In-place edit creates non-destructive branch and permits bidirectional shuttling."""
    engine = DualBranchingSessionEngine()
    session_id = "session-edit-branch-300"

    m1 = engine.append_message(session_id, role="system", content="System Setup")
    m2 = engine.append_message(session_id, role="user", content="Original Prompt A")
    m3 = engine.append_message(session_id, role="assistant", content="Original Output A")
    m4 = engine.append_message(session_id, role="user", content="Follow-up on A")

    # Active branch is initially main
    initial_branch = engine.get_active_branch_id(session_id)
    assert len(engine.get_active_projected_timeline(session_id)) == 4

    # User decides to edit m2 in-place (Edit From Here)
    m2_v2 = engine.edit_from_here(
        session_id=session_id,
        target_message_id=m2.message_id,
        new_role="user",
        new_content="Refined Prompt B (Better constraint)",
    )

    # Active branch is now switched to newly created branch
    v2_branch = engine.get_active_branch_id(session_id)
    assert v2_branch != initial_branch
    assert m2_v2.parent_id == m1.message_id  # Attached to same parent as original m2

    # Append response in new branch
    m3_v2 = engine.append_message(session_id, role="assistant", content="New Output B following constraints")

    # Projected timeline under v2 branch
    v2_timeline = engine.get_active_projected_timeline(session_id)
    assert len(v2_timeline) == 3
    assert [m.content for m in v2_timeline] == [
        "System Setup",
        "Refined Prompt B (Better constraint)",
        "New Output B following constraints",
    ]

    # Switch back to initial branch version 1 -> Zero historical data lost!
    engine.switch_active_branch(session_id, initial_branch)
    v1_timeline = engine.get_active_projected_timeline(session_id)
    assert len(v1_timeline) == 4
    assert [m.content for m in v1_timeline] == [
        "System Setup",
        "Original Prompt A",
        "Original Output A",
        "Follow-up on A",
    ]

    # Inspect version navigation pagination for the siblings under m1
    nav_v1 = engine.get_version_navigation_for_node(session_id, parent_id=m1.message_id)
    assert nav_v1.total_versions == 2
    assert nav_v1.current_version_index == 1
    assert nav_v1.active_message_id == m2.message_id

    # Switch to v2 and re-inspect navigation capsule
    engine.switch_active_branch(session_id, v2_branch)
    nav_v2 = engine.get_version_navigation_for_node(session_id, parent_id=m1.message_id)
    assert nav_v2.total_versions == 2
    assert nav_v2.current_version_index == 2
    assert nav_v2.active_message_id == m2_v2.message_id


def test_exception_handling_on_invalid_identifiers() -> None:
    """Verifies that queries with invalid IDs raise appropriate KeyErrors."""
    engine = DualBranchingSessionEngine()

    with pytest.raises(KeyError, match="Source session 'unknown' not found"):
        engine.new_session_from_here("unknown", "msg-x", "sess-new")

    with pytest.raises(KeyError, match="Session 'unknown' not found"):
        engine.edit_from_here("unknown", "msg-x", "user", "test")

    with pytest.raises(KeyError, match="Session 'unknown' not found"):
        engine.switch_active_branch("unknown", "branch-x")
