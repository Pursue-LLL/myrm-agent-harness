"""Tests for commitment type definitions and validation."""

import pytest
from pydantic import ValidationError

from myrm_agent_harness.toolkits.memory.proactive.types import (
    CommitmentCandidate,
    CommitmentDueWindow,
    CommitmentKind,
    CommitmentRecord,
    CommitmentSensitivity,
    CommitmentStatus,
    ExtractionBatchResult,
    is_active_status,
)


class TestEnums:
    def test_commitment_kind_values(self) -> None:
        assert CommitmentKind.EVENT_CHECK_IN == "event_check_in"
        assert CommitmentKind.DEADLINE_CHECK == "deadline_check"
        assert CommitmentKind.CARE_CHECK_IN == "care_check_in"
        assert CommitmentKind.OPEN_LOOP == "open_loop"
        assert len(CommitmentKind) == 4

    def test_commitment_sensitivity_values(self) -> None:
        assert CommitmentSensitivity.ROUTINE == "routine"
        assert CommitmentSensitivity.PERSONAL == "personal"
        assert CommitmentSensitivity.CARE == "care"
        assert len(CommitmentSensitivity) == 3

    def test_commitment_status_values(self) -> None:
        assert CommitmentStatus.PENDING == "pending"
        assert CommitmentStatus.SENT == "sent"
        assert CommitmentStatus.DISMISSED == "dismissed"
        assert CommitmentStatus.SNOOZED == "snoozed"
        assert CommitmentStatus.EXPIRED == "expired"
        assert len(CommitmentStatus) == 5


class TestIsActiveStatus:
    def test_pending_is_active(self) -> None:
        assert is_active_status(CommitmentStatus.PENDING) is True

    def test_snoozed_is_active(self) -> None:
        assert is_active_status(CommitmentStatus.SNOOZED) is True

    def test_sent_is_not_active(self) -> None:
        assert is_active_status(CommitmentStatus.SENT) is False

    def test_dismissed_is_not_active(self) -> None:
        assert is_active_status(CommitmentStatus.DISMISSED) is False

    def test_expired_is_not_active(self) -> None:
        assert is_active_status(CommitmentStatus.EXPIRED) is False


class TestDueWindow:
    def test_minimal_due_window(self) -> None:
        w = CommitmentDueWindow(earliest_ms=1000, latest_ms=2000)
        assert w.earliest_ms == 1000
        assert w.latest_ms == 2000
        assert w.timezone == "UTC"

    def test_custom_timezone(self) -> None:
        w = CommitmentDueWindow(
            earliest_ms=100, latest_ms=200, timezone="Asia/Shanghai"
        )
        assert w.timezone == "Asia/Shanghai"


class TestCommitmentRecord:
    def test_default_fields(self) -> None:
        rec = CommitmentRecord(
            agent_id="agent1",
            user_id="user1",
            kind=CommitmentKind.OPEN_LOOP,
            sensitivity=CommitmentSensitivity.ROUTINE,
            reason="test reason",
            suggested_text="Hey, any update?",
            dedupe_key="test:001",
            confidence=0.8,
            due_window=CommitmentDueWindow(earliest_ms=1000, latest_ms=2000),
        )
        assert rec.id.startswith("cm_")
        assert rec.status == CommitmentStatus.PENDING
        assert rec.channel == "web"
        assert rec.attempts == 0
        assert rec.snoozed_until_ms is None

    def test_confidence_range_validation(self) -> None:
        with pytest.raises(ValidationError):
            CommitmentRecord(
                agent_id="a",
                user_id="u",
                kind=CommitmentKind.OPEN_LOOP,
                sensitivity=CommitmentSensitivity.ROUTINE,
                reason="r",
                suggested_text="s",
                dedupe_key="d",
                confidence=1.5,
                due_window=CommitmentDueWindow(earliest_ms=1, latest_ms=2),
            )


class TestCommitmentCandidate:
    def test_valid_candidate(self) -> None:
        c = CommitmentCandidate(
            kind=CommitmentKind.EVENT_CHECK_IN,
            sensitivity=CommitmentSensitivity.PERSONAL,
            reason="Interview on Friday",
            suggested_text="Good luck with the interview!",
            dedupe_key="interview:2026-05-23",
            confidence=0.85,
            due_window_earliest="2026-05-23T09:00:00Z",
        )
        assert c.kind == CommitmentKind.EVENT_CHECK_IN
        assert c.due_window_latest is None
        assert c.due_window_timezone is None

    def test_negative_confidence_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CommitmentCandidate(
                kind=CommitmentKind.OPEN_LOOP,
                sensitivity=CommitmentSensitivity.ROUTINE,
                reason="r",
                suggested_text="s",
                dedupe_key="d",
                confidence=-0.1,
                due_window_earliest="2026-05-23T09:00:00Z",
            )


class TestExtractionBatchResult:
    def test_empty_default(self) -> None:
        r = ExtractionBatchResult()
        assert r.candidates == []

    def test_with_candidates(self) -> None:
        c = CommitmentCandidate(
            kind=CommitmentKind.CARE_CHECK_IN,
            sensitivity=CommitmentSensitivity.CARE,
            reason="Mom is sick",
            suggested_text="How's your mom doing?",
            dedupe_key="mom-health:2026-05-19",
            confidence=0.92,
            due_window_earliest="2026-05-21T09:00:00Z",
        )
        r = ExtractionBatchResult(candidates=[c])
        assert len(r.candidates) == 1
        assert r.candidates[0].sensitivity == CommitmentSensitivity.CARE
