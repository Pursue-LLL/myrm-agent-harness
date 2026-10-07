# ============================================================================
# Unit Tests for Session Tree Fork Branch & In-Place Rewind Engine (Item 162)
# ============================================================================

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management.session_tree import (
    ForkModeKind,
    ForkResult,
    RewindModeKind,
    RewindResult,
    SessionBranchNode,
    SessionMessageItem,
    SessionTreeRewindEngine,
    SessionTreeTopology,
)


def test_message_sequence_and_root_registration() -> None:
    """Validate message append increments sequence and automatically binds root branch."""
    engine = SessionTreeRewindEngine()

    m1 = engine.add_message("session-main", "user", "Hello agent")
    m2 = engine.add_message("session-main", "assistant", "Hello user", metadata={"model": "gpt-4o"})

    assert m1.sequence_index == 1
    assert m2.sequence_index == 2
    assert m2.metadata.get("model") == "gpt-4o"

    msgs = engine.get_messages("session-main")
    assert len(msgs) == 2
    assert msgs[0].message_id == m1.message_id
    assert msgs[1].message_id == m2.message_id

    topology = engine.get_tree_topology("session-main")
    assert topology.root_session_id == "session-main"
    assert len(topology.branches) == 1
    assert topology.branches[0].branch_name == "main"


def test_fork_at_message_antecedent_slicing() -> None:
    """Validate forking from arbitrary message node cleanly slices antecedent history."""
    engine = SessionTreeRewindEngine()

    # Create 4 chronological turns
    m1 = engine.add_message("session-root", "user", "Proposal brainstorm")
    m2 = engine.add_message("session-root", "assistant", "Option A (SQLite) vs Option B (Redis)")
    m3 = engine.add_message("session-root", "user", "Let's proceed with SQLite")
    m4 = engine.add_message("session-root", "assistant", "Implementing SQLite schema...")

    # Fork from m2 node into a new Redis exploration branch
    fork_res = engine.fork_at_message(
        source_session_id="session-root",
        target_message_id=m2.message_id,
        new_branch_name="redis-branch",
        fork_mode=ForkModeKind.DEEP_CLONE,
    )

    assert fork_res.parent_session_id == "session-root"
    assert fork_res.fork_message_id == m2.message_id
    assert fork_res.cloned_messages_count == 2
    assert fork_res.new_session_id.startswith("session-fork-")

    # Validate cloned messages in the new branch
    forked_msgs = engine.get_messages(fork_res.new_session_id)
    assert len(forked_msgs) == 2
    assert forked_msgs[0].content == "Proposal brainstorm"
    assert forked_msgs[1].content == "Option A (SQLite) vs Option B (Redis)"
    # Cloned IDs must differ from parents
    assert forked_msgs[0].message_id != m1.message_id
    assert forked_msgs[1].message_id != m2.message_id

    # Append to new branch: ensure complete isolation from root branch
    engine.add_message(fork_res.new_session_id, "user", "Let's proceed with Redis instead")
    assert len(engine.get_messages(fork_res.new_session_id)) == 3
    assert len(engine.get_messages("session-root")) == 4


def test_in_place_message_rewind_and_prompt_restore() -> None:
    """Validate in-place timeline rewind truncates history and extracts prompt for editing."""
    engine = SessionTreeRewindEngine()

    m1 = engine.add_message("session-dev", "user", "Create a snake game")
    m2 = engine.add_message("session-dev", "assistant", "Here is Python snake code...")
    m3 = engine.add_message("session-dev", "user", "Rewrite it in React please")
    m4 = engine.add_message("session-dev", "assistant", "Here is React snake component...")

    # User realizes typo/constraint error on m3, triggers in-place rewind
    rewind_res = engine.rewind_to_message(
        session_id="session-dev",
        target_message_id=m3.message_id,
        rewind_mode=RewindModeKind.TRUNCATE_AND_ARCHIVE,
    )

    assert rewind_res.target_message_id == m3.message_id
    assert rewind_res.removed_messages_count == 2  # m3 and m4 removed
    assert rewind_res.restored_prompt_text == "Rewrite it in React please"
    assert m3.message_id in rewind_res.archived_message_ids
    assert m4.message_id in rewind_res.archived_message_ids

    # Active messages in session-dev must now only retain m1 and m2
    active_msgs = engine.get_messages("session-dev")
    assert len(active_msgs) == 2
    assert [m.message_id for m in active_msgs] == [m1.message_id, m2.message_id]


def test_multi_branch_tree_topology() -> None:
    """Validate multi-tier hierarchical tree topology lineage resolution."""
    engine = SessionTreeRewindEngine()

    # Root branch
    r1 = engine.add_message("sess-root", "user", "Base prompt")
    r2 = engine.add_message("sess-root", "assistant", "Base reply")

    # Branch 1 from root
    fork1 = engine.fork_at_message("sess-root", r2.message_id, "feature-auth")
    b1_msg = engine.add_message(fork1.new_session_id, "user", "Auth design")

    # Branch 2 sub-forked from Branch 1
    fork2 = engine.fork_at_message(fork1.new_session_id, b1_msg.message_id, "feature-auth-passkey")

    # Retrieve tree topology from sub-branch
    topology = engine.get_tree_topology(fork2.new_session_id)
    assert topology.root_session_id == "sess-root"
    assert topology.active_session_id == fork2.new_session_id
    assert len(topology.branches) == 3

    branch_names = [b.branch_name for b in topology.branches]
    assert "main" in branch_names
    assert "feature-auth" in branch_names
    assert "feature-auth-passkey" in branch_names
