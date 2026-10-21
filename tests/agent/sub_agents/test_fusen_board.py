"""Unit tests for Lightweight Fusen Shared State Sync (Item 63).

[INPUT]
- FusenSharedBoard, FusenNote, FusenCategory, NoteStatus.

[OUTPUT]
- Pytest test cases verifying sub-millisecond sticky-note posting, filtering,
  blocker checks, TTL expiration, and resolution flows.

[POS]
- myrm-agent-harness/tests/agent/sub_agents/test_fusen_board.py
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.sub_agents.fusen import (
    FusenCategory,
    FusenSharedBoard,
    NoteStatus,
)


@pytest.fixture
def board() -> FusenSharedBoard:
    """Fixture providing a fresh FusenSharedBoard instance."""
    b = FusenSharedBoard()
    b.clear()
    return b


def test_post_and_get_note(board: FusenSharedBoard) -> None:
    """Test posting a sticky note and retrieving it by note_id."""
    note = board.post_note(
        note_id="note-001",
        session_id="sess-alpha",
        author_agent_id="worker-coder",
        category=FusenCategory.READY_FOR_REVIEW,
        tag="ready_for_review: diff_auth_module",
        content="Completed JWT authentication logic in src/auth.py.",
        metadata={"lines_added": "42"},
    )

    assert note.note_id == "note-001"
    assert note.session_id == "sess-alpha"
    assert note.author_agent_id == "worker-coder"
    assert note.category == FusenCategory.READY_FOR_REVIEW
    assert note.tag == "ready_for_review: diff_auth_module"
    assert note.status == NoteStatus.ACTIVE
    assert note.metadata["lines_added"] == "42"

    retrieved = board.get_note("note-001")
    assert retrieved is not None
    assert retrieved.note_id == "note-001"


def test_resolve_note(board: FusenSharedBoard) -> None:
    """Test resolving an active note with resolution notes."""
    board.post_note(
        note_id="note-blocker-1",
        session_id="sess-beta",
        author_agent_id="worker-db",
        category=FusenCategory.BLOCKER,
        tag="blocked_by: database_schema_lock",
        content="Waiting for migration to complete.",
    )

    resolved = board.resolve_note(
        note_id="note-blocker-1",
        resolution_note="Migration finished successfully. Schema lock released.",
    )

    assert resolved.status == NoteStatus.RESOLVED
    assert resolved.resolution_note == "Migration finished successfully. Schema lock released."

    # By default, resolved notes are excluded from list_notes unless requested
    active_notes = board.list_notes(session_id="sess-beta", include_resolved=False)
    assert len(active_notes) == 0

    all_notes = board.list_notes(session_id="sess-beta", include_resolved=True)
    assert len(all_notes) == 1
    assert all_notes[0].status == NoteStatus.RESOLVED


def test_list_notes_with_filters(board: FusenSharedBoard) -> None:
    """Test multi-dimensional filtering by category, tag_prefix, and session."""
    board.post_note(
        note_id="n1",
        session_id="sess-1",
        author_agent_id="agent-1",
        category=FusenCategory.CACHE_HINT,
        tag="cache_hit: docker_layer_builder",
    )
    board.post_note(
        note_id="n2",
        session_id="sess-1",
        author_agent_id="agent-2",
        category=FusenCategory.IN_PROGRESS,
        tag="in_progress: writing_unit_tests",
    )
    board.post_note(
        note_id="n3",
        session_id="sess-2",
        author_agent_id="agent-3",
        category=FusenCategory.CACHE_HINT,
        tag="cache_hit: npm_cache",
    )

    # Filter by session
    sess1_notes = board.list_notes(session_id="sess-1")
    assert len(sess1_notes) == 2

    # Filter by category
    cache_notes = board.list_notes(category=FusenCategory.CACHE_HINT)
    assert len(cache_notes) == 2

    # Filter by tag prefix
    in_prog = board.list_notes(tag_prefix="in_progress:")
    assert len(in_prog) == 1
    assert in_prog[0].note_id == "n2"


def test_check_blockers_and_target_filtering(board: FusenSharedBoard) -> None:
    """Test rapid sub-millisecond blocker check with target agent resolution."""
    # Initially no blockers
    summary0 = board.check_blockers("sess-test")
    assert summary0.is_blocked is False
    assert summary0.blocker_count == 0

    # Post a global blocker
    board.post_note(
        note_id="blk-global",
        session_id="sess-test",
        author_agent_id="lead-agent",
        category=FusenCategory.BLOCKER,
        tag="blocked_by: payment_api_downtime",
    )

    summary1 = board.check_blockers("sess-test")
    assert summary1.is_blocked is True
    assert summary1.blocker_count == 1
    assert "blocked_by: payment_api_downtime" in summary1.active_tags

    # Post an agent-targeted blocker (only affects worker-special)
    board.post_note(
        note_id="blk-targeted",
        session_id="sess-test",
        author_agent_id="lead-agent",
        category=FusenCategory.BLOCKER,
        tag="blocked_by: license_key_quota",
        metadata={"target_agent_id": "worker-special"},
    )

    # Query for other worker
    summary_other = board.check_blockers("sess-test", target_agent_id="worker-other")
    assert summary_other.blocker_count == 1  # only global

    # Query for target worker
    summary_target = board.check_blockers("sess-test", target_agent_id="worker-special")
    assert summary_target.blocker_count == 2  # global + targeted


def test_ttl_and_cleanup_expired(board: FusenSharedBoard) -> None:
    """Test sticky note TTL expiration and automatic cleanup."""
    note = board.post_note(
        note_id="temp-note",
        session_id="sess-ttl",
        author_agent_id="temp-agent",
        category=FusenCategory.CUSTOM,
        tag="temp_hint",
        ttl_seconds=10.0,
    )

    # Initially not expired
    assert note.is_expired(now=note.created_at + 5.0) is False

    # Expired after 15s
    assert note.is_expired(now=note.created_at + 15.0) is True

    # List notes simulated in future
    assert len(board.list_notes(session_id="sess-ttl")) == 1

    # Cleanup expired
    pruned = board.cleanup_expired(now=note.created_at + 20.0)
    assert pruned == 1
    assert board.get_note("temp-note") is None


def test_resolve_non_existent_note_raises(board: FusenSharedBoard) -> None:
    """Test resolving a non-existent note raises KeyError."""
    with pytest.raises(KeyError, match="not found"):
        board.resolve_note("invalid-id", "some resolution")
