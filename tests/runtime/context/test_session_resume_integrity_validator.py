"""Unit tests for Session State Write-Failure Self-Healing & Resume Validator (Item 35)."""

from myrm_agent_harness.runtime.context.session_resume_integrity_validator import (
    AnomalyKind,
    SessionResumeValidator,
    SessionTurnRecord,
)


def test_perfect_session_passes_validation() -> None:
    """Verifies that an intact, fully-persisted session passes validation with zero repairs."""
    turns: list[SessionTurnRecord] = [
        SessionTurnRecord(turn_id="t0", turn_index=0, role="user", content="Search error logs"),
        SessionTurnRecord(
            turn_id="t1",
            turn_index=1,
            role="assistant",
            content="Invoking grep",
            tool_call_ids=["call_grep_01"],
            status="completed",
        ),
        SessionTurnRecord(
            turn_id="t2",
            turn_index=2,
            role="tool",
            content="Found 0 matches",
            tool_result_id="call_grep_01",
            status="completed",
        ),
        SessionTurnRecord(
            turn_id="t3",
            turn_index=3,
            role="assistant",
            content="No errors found.",
            status="completed",
        ),
    ]

    healed_turns, report = SessionResumeValidator.validate_and_heal("sess_intact_1", turns)

    assert report.is_valid
    assert report.can_resume
    assert not report.auto_healed
    assert report.repaired_count == 0
    assert len(report.anomalies) == 0
    assert len(healed_turns) == 4
    assert [t.turn_index for t in healed_turns] == [0, 1, 2, 3]


def test_sequence_gap_auto_repair() -> None:
    """Verifies detection and re-sequencing when sequence gaps exist due to uncommitted drops."""
    turns: list[SessionTurnRecord] = [
        SessionTurnRecord(turn_id="t0", turn_index=0, role="user", content="Step 1"),
        SessionTurnRecord(turn_id="t1", turn_index=1, role="assistant", content="Step 2"),
        # Gap: turn_index jumps from 1 to 5
        SessionTurnRecord(turn_id="t2", turn_index=5, role="user", content="Step 3"),
        SessionTurnRecord(turn_id="t3", turn_index=6, role="assistant", content="Step 4"),
    ]

    healed_turns, report = SessionResumeValidator.validate_and_heal("sess_gap_1", turns)

    assert not report.is_valid
    assert report.auto_healed
    assert report.can_resume
    assert report.repaired_count == 2
    assert any(a.kind == AnomalyKind.SEQUENCE_GAP for a in report.anomalies)

    # Verifies normalized continuous sequence post-repair
    assert [t.turn_index for t in healed_turns] == [0, 1, 2, 3]


def test_unclosed_tool_call_compensation_healing() -> None:
    """Verifies synthetic compensation injection when process crash left tool write unpersisted."""
    turns: list[SessionTurnRecord] = [
        SessionTurnRecord(turn_id="t0", turn_index=0, role="user", content="Run multi tools"),
        SessionTurnRecord(
            turn_id="t1",
            turn_index=1,
            role="assistant",
            content="Running two tools",
            tool_call_ids=["call_tool_a", "call_tool_b"],
            status="completed",
        ),
        # Only call_tool_a was written; call_tool_b was interrupted before write
        SessionTurnRecord(
            turn_id="t2",
            turn_index=2,
            role="tool",
            content="Result A",
            tool_result_id="call_tool_a",
            status="completed",
        ),
    ]

    healed_turns, report = SessionResumeValidator.validate_and_heal("sess_crash_1", turns)

    assert not report.is_valid
    assert report.auto_healed
    assert report.can_resume
    assert any(a.kind == AnomalyKind.UNCLOSED_TOOL_CALL for a in report.anomalies)

    # 4 turns total: t0, t1, t2, and synthetic compensation turn for call_tool_b
    assert len(healed_turns) == 4
    comp_turn = healed_turns[3]
    assert comp_turn.role == "tool"
    assert comp_turn.tool_result_id == "call_tool_b"
    assert comp_turn.status == "interrupted_resumed"
    assert "Resume Compensation" in comp_turn.content
    assert [t.turn_index for t in healed_turns] == [0, 1, 2, 3]


def test_pending_turn_auto_finalization() -> None:
    """Verifies that an interrupted pending turn is cleanly finalized before resuming next run."""
    turns: list[SessionTurnRecord] = [
        SessionTurnRecord(turn_id="t0", turn_index=0, role="user", content="Query"),
        SessionTurnRecord(
            turn_id="t1",
            turn_index=1,
            role="assistant",
            content="Generating partial output...",
            status="pending",
        ),
    ]

    healed_turns, report = SessionResumeValidator.validate_and_heal("sess_pending_1", turns)

    assert not report.is_valid
    assert report.auto_healed
    assert report.can_resume
    assert any(a.kind == AnomalyKind.PARTIAL_TURN_RECORD for a in report.anomalies)
    assert healed_turns[1].status == "interrupted_resumed"


def test_empty_session_validation() -> None:
    """Verifies that empty sessions return a clean valid report."""
    healed_turns, report = SessionResumeValidator.validate_and_heal(
        "sess_empty_1", []
    )

    assert report.is_valid
    assert report.can_resume
    assert not report.auto_healed
    assert len(healed_turns) == 0
