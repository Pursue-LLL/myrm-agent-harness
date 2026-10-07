"""Unit tests for DevFlow Context Lifecycle and Progressive Loading Suite.

Verifies the 4-Question Gate admission heuristics, strict <= 500 char exploration handoff bounds,
phase transitions with transient token purges, deliverable template progressive loading, and telemetry.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management import (
    ContextAdmissionDecision,
    ContextGateEvaluator,
    DevFlowContextLifecycleAndProgressiveLoadingSuite,
    DevFlowPhase,
    ExplorationHandoffEngine,
    GateQuestionnaireEvaluation,
    PhaseLifecycleState,
    StructuredExplorationHandoff,
)


def test_context_gate_evaluator_four_questions() -> None:
    """Verify evaluation of candidate content against the 4-Question Gate."""
    evaluator = ContextGateEvaluator()

    # 1. Not required for current phase -> DEFER_PROGRESSIVE
    res_phase = evaluator.evaluate_admission(
        current_phase=DevFlowPhase.PLANNING,
        intended_phase=DevFlowPhase.DELIVERY,
        content_length=500,
    )
    assert res_phase.decision == ContextAdmissionDecision.DEFER_PROGRESSIVE
    assert not res_phase.is_required_for_current_phase

    # 2. Single-use exploratory search -> ISOLATE_SCRATCHPAD
    res_single_use = evaluator.evaluate_admission(
        current_phase=DevFlowPhase.EXPLORATION,
        intended_phase=DevFlowPhase.EXPLORATION,
        content_length=3000,
        is_single_use=True,
    )
    assert res_single_use.decision == ContextAdmissionDecision.ISOLATE_SCRATCHPAD
    assert res_single_use.is_single_use_reference

    # 3. Explicit trigger condition not satisfied -> DEFER_PROGRESSIVE
    res_trigger = evaluator.evaluate_admission(
        current_phase=DevFlowPhase.IMPLEMENTATION,
        intended_phase=DevFlowPhase.IMPLEMENTATION,
        content_length=400,
        has_trigger_condition=True,
        trigger_satisfied=False,
    )
    assert res_trigger.decision == ContextAdmissionDecision.DEFER_PROGRESSIVE

    # 4. Large content fetchable externally -> EXTERNAL_REFERENCE_ONLY
    res_external = evaluator.evaluate_admission(
        current_phase=DevFlowPhase.IMPLEMENTATION,
        intended_phase=DevFlowPhase.IMPLEMENTATION,
        content_length=1500,
        can_external_lookup=True,
    )
    assert res_external.decision == ContextAdmissionDecision.EXTERNAL_REFERENCE_ONLY
    assert res_external.can_be_retrieved_externally

    # 5. Core required knowledge passing all questions -> INLINE_ALLOW
    res_allow = evaluator.evaluate_admission(
        current_phase=DevFlowPhase.IMPLEMENTATION,
        intended_phase=DevFlowPhase.IMPLEMENTATION,
        content_length=300,
        can_external_lookup=False,
    )
    assert res_allow.decision == ContextAdmissionDecision.INLINE_ALLOW


def test_exploration_handoff_engine_strict_bound() -> None:
    """Verify creation and strict <= 500 character constraint of structured exploration handoffs."""
    engine = ExplorationHandoffEngine()

    handoff = engine.create_structured_handoff(
        direct_verdict="Session persistence layer requires schema upgrade to support varint offsets.",
        target_components=["SessionPersistence", "SQLiteEventStream", "VarintIndexer"],
        key_findings=[
            "Found table lock bottlenecks in models/chat.py",
            "Discovered unindexed timestamp column causing full table scans",
            "Verified backward compatibility with existing migration scripts",
        ],
        impacted_files=[
            "src/models/chat.py",
            "src/services/session_stream.py",
            "migrations/004_varint.sql",
        ],
        architectural_risks=["Potential lock contention during high concurrency"],
    )

    rendered = handoff.render_markdown_card()
    assert len(rendered) <= 500
    assert handoff.is_within_bound
    assert "### 🔍 Exploration Handoff Synthesis" in rendered
    assert "SessionPersistence" in rendered
    assert "models/chat.py" in rendered


def test_devflow_lifecycle_suite_transitions_and_telemetry() -> None:
    """Verify master suite phase progression, deliverable mounting, token purging, and telemetry."""
    suite = DevFlowContextLifecycleAndProgressiveLoadingSuite()

    # 1. Start session at PLANNING phase
    s0 = suite.get_or_create_state("sess-flow-1")
    assert s0.current_phase == DevFlowPhase.PLANNING
    assert "developer-deliverables.md" not in s0.active_deliverable_templates

    # 2. Advance to EXPLORATION
    s1 = suite.transition_phase("sess-flow-1", DevFlowPhase.EXPLORATION)
    assert s1.current_phase == DevFlowPhase.EXPLORATION

    # 3. Complete exploration: attach structured handoff and transition to IMPLEMENTATION with token purge
    handoff = suite.handoff_engine.create_structured_handoff(
        direct_verdict="Confirmed auth middleware refactor strategy.",
        target_components=["AuthMiddleware"],
        key_findings=["JWT expiration logic clean", "Need unit test coverage"],
        impacted_files=["auth/middleware.py"],
    )
    suite.attach_exploration_handoff("sess-flow-1", handoff)

    # Purging 8,500 raw grep/find tokens accumulated during exploration
    s2 = suite.transition_phase("sess-flow-1", DevFlowPhase.IMPLEMENTATION, purged_tokens_estimate=8500)
    assert s2.current_phase == DevFlowPhase.IMPLEMENTATION
    assert s2.purged_raw_tokens_count == 8500
    assert len(s2.retained_handoffs) == 1

    # 4. Advance to DELIVERY: template should mount progressively
    s3 = suite.transition_phase("sess-flow-1", DevFlowPhase.DELIVERY)
    assert s3.current_phase == DevFlowPhase.DELIVERY
    assert "developer-deliverables.md" in s3.active_deliverable_templates

    # 5. Global telemetry check
    telemetry = suite.get_global_telemetry()
    assert telemetry["active_sessions"] == 1
    assert telemetry["total_exploration_handoffs"] == 1
    assert telemetry["total_purged_raw_tokens"] == 8500
