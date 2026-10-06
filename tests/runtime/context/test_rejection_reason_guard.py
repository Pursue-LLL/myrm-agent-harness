"""Unit tests for Human Rejection Reason Capture & Anti-Regression Guard (Item 30)."""

from myrm_agent_harness.runtime.context.rejection_reason_guard import (
    AvoidanceConstraint,
    HumanRejectionEvent,
    HumanRejectionGuard,
    RejectionCategory,
)


def test_record_rejection_stores_event_with_metadata() -> None:
    """Verifies human rejection recording stores categories, semantic reasons, and notes."""
    guard = HumanRejectionGuard(session_id="sess-reject-01")

    event: HumanRejectionEvent = guard.record_rejection(
        target_artifact_id="art-ui-button",
        rejected_version=3,
        category=RejectionCategory.STYLE_REGRESSION,
        semantic_reason="Broke existing button margin and color gradient",
        user_note="Button is overlapping input field",
        rejected_diff_snippet="- margin: 8px;\n+ margin: 0px;",
    )

    assert event.event_id.startswith("rej-")
    assert event.target_artifact_id == "art-ui-button"
    assert event.rejected_version == 3
    assert event.category == RejectionCategory.STYLE_REGRESSION
    assert event.semantic_reason == "Broke existing button margin and color gradient"
    assert event.user_note == "Button is overlapping input field"

    recent = guard.get_recent_rejections()
    assert len(recent) == 1
    assert recent[0].event_id == event.event_id


def test_distill_avoidance_constraints() -> None:
    """Verifies conversion of raw rejections into actionable avoidance directives."""
    guard = HumanRejectionGuard(session_id="sess-reject-02")

    guard.record_rejection(
        target_artifact_id="api_client.py",
        rejected_version=2,
        category=RejectionCategory.MISSED_EDGE_CASE,
        semantic_reason="Unhandled HTTP 429 rate limit",
        user_note="Need exponential backoff retry",
    )
    guard.record_rejection(
        target_artifact_id="routes.py",
        rejected_version=5,
        category=RejectionCategory.WRONG_TARGET,
        semantic_reason="Edited user profile route instead of billing route",
    )

    constraints: list[AvoidanceConstraint] = guard.distill_avoidance_constraints(limit=10)
    assert len(constraints) == 2

    c1 = constraints[0]
    assert c1.category == RejectionCategory.MISSED_EDGE_CASE
    assert "MUST explicitly handle boundary conditions" in c1.directive
    assert "Unhandled HTTP 429 rate limit" in c1.directive
    assert "Need exponential backoff retry" in c1.directive

    c2 = constraints[1]
    assert c2.category == RejectionCategory.WRONG_TARGET
    assert "DO NOT edit unrelated modules" in c2.directive


def test_format_avoidance_prompt_block() -> None:
    """Verifies that avoidance constraints format into structured model-readable context blocks."""
    guard = HumanRejectionGuard(session_id="sess-reject-03")
    guard.record_rejection(
        target_artifact_id="schema.sql",
        rejected_version=1,
        category=RejectionCategory.BREAKING_CONTRACT,
        semantic_reason="Dropped non-null column without default value",
    )

    prompt_block = guard.format_avoidance_prompt_block()
    assert "<!-- HUMAN REJECTION ANTI-REGRESSION CONSTRAINTS -->" in prompt_block
    assert "Artifact 'schema.sql' (rejected v1, category: breaking_contract):" in prompt_block
    assert "DO NOT break existing function signatures, public API contracts, or protocols" in prompt_block
    assert "<!-- END ANTI-REGRESSION CONSTRAINTS -->" in prompt_block


def test_empty_rejections_graceful_fallback() -> None:
    """Verifies empty rejection history gracefully yields blank prompt blocks and lists."""
    guard = HumanRejectionGuard(session_id="sess-empty")
    assert guard.distill_avoidance_constraints() == []
    assert guard.format_avoidance_prompt_block() == ""


def test_validate_plan_against_constraints() -> None:
    """Verifies pre-flight checks detect proposals that risk repeating rejected blunders."""
    guard = HumanRejectionGuard(session_id="sess-reject-04")
    guard.record_rejection(
        target_artifact_id="config.py",
        rejected_version=4,
        category=RejectionCategory.CUSTOM_FEEDBACK,
        semantic_reason="Hardcoded production token",
        user_note="do not use hardcoded tokens",
    )

    # Valid plan that adheres to constraints
    valid, msg = guard.validate_plan_against_constraints("Load token from environment variables")
    assert valid is True
    assert msg == ""

    # Problematic plan that repeats user feedback keywords
    invalid, err_msg = guard.validate_plan_against_constraints("We will temporarily do not use hardcoded tokens bypass")
    assert invalid is False
    assert "Plan conflicts with prior user feedback on v4" in err_msg
