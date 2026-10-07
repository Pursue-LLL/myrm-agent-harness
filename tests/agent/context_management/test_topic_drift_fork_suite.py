"""Unit tests for Topic Drift Demarcation and Auto-Renamed Session Fork Suite.

Verifies intent drift heuristic detection (domain divergence, milestone closure, explicit switches),
non-intrusive GUI suggestion banner generation, clean session forking with auto-renaming, and telemetry.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management import (
    DriftSignalKind,
    ForkExecutionResult,
    SessionForkManager,
    SessionForkSuggestion,
    TopicDriftDemarcationAndAutoRenamedSessionForkSuite,
    TopicDriftDetector,
    TopicDriftEvaluation,
)


def test_topic_drift_detector_heuristics_and_signals() -> None:
    """Verify topic drift detection across continuous, explicit shift, and cross-domain milestones."""
    detector = TopicDriftDetector(min_prolonged_turns=10, min_prolonged_tokens=10000)

    # 1. Normal continuous flow: same domain, short session
    eval_continuous = detector.evaluate_drift(
        session_id="sess-001",
        current_tokens=4000,
        turn_count=4,
        previous_topic="postgres database migration and indexing",
        current_prompt="Can you explain why the table lock query is timing out?",
        all_todos_completed=False,
    )
    assert not eval_continuous.is_drift_detected
    assert eval_continuous.confidence < 0.60
    assert len(eval_continuous.detected_signals) == 0

    # 2. Explicit transition pattern
    eval_explicit = detector.evaluate_drift(
        session_id="sess-001",
        current_tokens=5000,
        turn_count=5,
        previous_topic="postgres database migration",
        current_prompt="Now let's switch to designing the React login modal component.",
        all_todos_completed=False,
    )
    assert eval_explicit.is_drift_detected
    assert DriftSignalKind.EXPLICIT_TOPIC_CHANGE in eval_explicit.detected_signals
    assert eval_explicit.new_detected_topic == "Frontend"

    # 3. Cross-domain shift + milestone closure + prolonged session
    eval_composite = detector.evaluate_drift(
        session_id="sess-002",
        current_tokens=18000,
        turn_count=14,
        previous_topic="database postgres sql indexing",
        current_prompt="Write a React Tailwind CSS button component and modal dialog.",
        all_todos_completed=True,
    )
    assert eval_composite.is_drift_detected
    assert eval_composite.confidence >= 0.80
    assert DriftSignalKind.PROLONGED_SESSION in eval_composite.detected_signals
    assert DriftSignalKind.MILESTONE_COMPLETED in eval_composite.detected_signals
    assert DriftSignalKind.SEMANTIC_SHIFT in eval_composite.detected_signals


def test_session_fork_manager_suggestion_and_execution() -> None:
    """Verify recommendation generation and clean session forking execution."""
    manager = SessionForkManager()

    evaluation = TopicDriftEvaluation(
        session_id="sess-alpha",
        is_drift_detected=True,
        confidence=0.85,
        detected_signals=[DriftSignalKind.MILESTONE_COMPLETED, DriftSignalKind.SEMANTIC_SHIFT],
        previous_topic="Database Schema Migration",
        new_detected_topic="Frontend",
        current_tokens=22000,
        turn_count=16,
        reason="Detected completed todos and semantic shift to Frontend.",
    )

    # Generate recommendation
    suggestion = manager.generate_fork_suggestion(
        evaluation=evaluation,
        preceding_summary_snippet="Completed PostgreSQL schema migrations and table indexes.",
    )
    assert suggestion.old_session_id == "sess-alpha"
    assert suggestion.suggested_archived_title == "[Archived] Database Schema Migration"
    assert suggestion.suggested_new_title == "Frontend Workstream"
    assert suggestion.estimated_tokens_cleared == 22000
    assert "💡 Detected new goal [Frontend]" in suggestion.user_banner_message

    # Execute fork with default title
    fork_res = manager.execute_fork(suggestion)
    assert fork_res.archived_session_id == "sess-alpha"
    assert fork_res.archived_title == "[Archived] Database Schema Migration"
    assert fork_res.new_session_id.startswith("sess-")
    assert fork_res.new_title == "Frontend Workstream"
    assert fork_res.tokens_relieved == 22000
    assert fork_res.attention_focus_gain_ratio == 2.0

    # Execute fork with custom title override
    custom_res = manager.execute_fork(suggestion, custom_new_title="User Dashboard UI")
    assert custom_res.new_title == "User Dashboard UI"


def test_topic_drift_fork_suite_lifecycle_and_metrics() -> None:
    """Verify master suite lifecycle evaluation, clean forking, and telemetry metrics."""
    suite = TopicDriftDemarcationAndAutoRenamedSessionForkSuite(
        min_prolonged_turns=10,
        min_prolonged_tokens=12000,
    )

    # Initial turn: continuing within current scope
    eval_1, sugg_1 = suite.evaluate_turn(
        session_id="sess-master",
        current_tokens=8000,
        turn_count=6,
        previous_topic="Backend API authentication",
        current_prompt="Check JWT token expiration format.",
    )
    assert not eval_1.is_drift_detected
    assert sugg_1 is None

    # Drift turn: all backend tasks done, switching to documentation
    eval_2, sugg_2 = suite.evaluate_turn(
        session_id="sess-master",
        current_tokens=15000,
        turn_count=12,
        previous_topic="auth jwt token permission",
        current_prompt="Write the complete Readme markdown guide and API docs tutorial.",
        all_todos_completed=True,
    )
    assert eval_2.is_drift_detected
    assert sugg_2 is not None
    assert sugg_2.suggested_archived_title == "[Archived] auth jwt token permission"
    assert sugg_2.suggested_new_title == "Documentation Workstream"

    # Execute fork
    result = suite.execute_fork(sugg_2)
    assert result.archived_session_id == "sess-master"
    assert result.tokens_relieved == 15000

    # Aggregate metrics
    metrics = suite.get_aggregate_metrics()
    assert metrics["total_forks_executed"] == 1
    assert metrics["total_tokens_relieved"] == 15000
    assert metrics["average_attention_focus_gain_ratio"] == 2.0
