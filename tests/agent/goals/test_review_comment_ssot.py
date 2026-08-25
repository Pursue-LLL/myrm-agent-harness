"""Tests for Verification Review Comments SSOT data structures and serialization."""

from __future__ import annotations

from myrm_agent_harness.agent.goals.verification.base import (
    AggregatedVerificationResult,
    ReviewComment,
    ReviewSeverity,
    VerificationResult,
)


def test_review_severity_values() -> None:
    assert ReviewSeverity.CRITICAL.value == "critical"
    assert ReviewSeverity.WARNING.value == "warning"
    assert ReviewSeverity.INFO.value == "info"


def test_review_comment_serialization_roundtrip() -> None:
    comment = ReviewComment(
        id="c1",
        severity=ReviewSeverity.WARNING,
        message="Code smells in verifier loop",
        target_path="app/core/kanban/verifier.py",
        line_range="100-115",
        fix_suggestion="Extract helper method for clarity",
    )

    data = comment.to_dict()
    assert data["severity"] == "warning"
    assert data["message"] == "Code smells in verifier loop"
    assert data["target_path"] == "app/core/kanban/verifier.py"
    assert data["line_range"] == "100-115"
    assert data["fix_suggestion"] == "Extract helper method for clarity"
    assert data["id"] == "c1"

    restored = ReviewComment.from_dict(data)
    assert restored.severity == ReviewSeverity.WARNING
    assert restored.message == comment.message
    assert restored.target_path == comment.target_path
    assert restored.line_range == comment.line_range
    assert restored.fix_suggestion == comment.fix_suggestion
    assert restored.id == comment.id


def test_review_comment_from_dict_defaults() -> None:
    minimal = {"message": "Syntax error"}
    comment = ReviewComment.from_dict(minimal)
    assert comment.message == "Syntax error"
    assert comment.severity == ReviewSeverity.CRITICAL
    assert comment.target_path is None
    assert comment.line_range is None
    assert comment.fix_suggestion is None
    assert comment.id is None


def test_verification_result_counts_and_dict() -> None:
    c_crit = ReviewComment(message="Critical fail", severity=ReviewSeverity.CRITICAL)
    c_warn = ReviewComment(message="Warning note", severity=ReviewSeverity.WARNING)
    c_info = ReviewComment(message="Info hint", severity=ReviewSeverity.INFO)

    vr = VerificationResult(
        passed=False,
        criterion_label="Shell check",
        reason="pytest failed",
        error_logs="assert 1 == 2",
        comments=[c_crit, c_warn, c_info],
    )

    assert vr.critical_count == 1
    assert vr.warning_count == 1
    assert vr.info_count == 1

    d = vr.to_dict()
    assert d["passed"] is False
    assert d["label"] == "Shell check"
    assert d["reason"] == "pytest failed"
    assert d["error_logs"] == "assert 1 == 2"
    assert len(d.get("comments", [])) == 3


def test_aggregated_verification_result_all_comments() -> None:
    c1 = ReviewComment(message="c1", severity=ReviewSeverity.CRITICAL)
    c2 = ReviewComment(message="c2", severity=ReviewSeverity.INFO)

    vr1 = VerificationResult(passed=False, comments=[c1])
    vr2 = VerificationResult(passed=True, comments=[c2])

    agg = AggregatedVerificationResult(passed=False, per_criterion=[vr1, vr2])
    assert agg.failed_count == 1
    assert len(agg.all_comments) == 2
    assert agg.all_comments[0].message == "c1"
    assert agg.all_comments[1].message == "c2"
