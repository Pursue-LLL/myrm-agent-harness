"""
[POS] tests/unit/test_auto_review_resolution_suite.py
[INPUT] myrm_agent_harness.core.security.auto_review_resolution
[OUTPUT] Unit test suite for Auto-Review Denial Four-Way Adaptive Resolution State Machine

Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from myrm_agent_harness.core.security.auto_review_resolution import (
    AutoReviewResolutionFacade,
    DenialDiagnosticReporter,
    DenialReasonCodeEnum,
    FourWayResolutionStateMachine,
    HandoverDeckManager,
    HandoverStatusEnum,
    ResolutionBranchEnum,
)


def test_diagnostic_reporter_inference() -> None:
    """Test structured diagnostic generation with automated alternative inference."""
    # 1. High risk action defaults to HANDOVER_TO_USER
    diag_high = DenialDiagnosticReporter.generate_diagnostic(
        blocked_action="deploy_k8s_cluster",
        denial_reason="Direct production cluster mutation denied by policy.",
        reason_code=DenialReasonCodeEnum.HIGH_RISK_ACTION,
        policy_rule_id="RULE-PROD-01",
        context_data={"env": "production"},
    )
    assert diag_high.suggested_branch == ResolutionBranchEnum.HANDOVER_TO_USER
    assert len(diag_high.allowed_alternatives) > 0
    assert "generate staged dry-run diff preview" in diag_high.allowed_alternatives

    # 2. Unauthorized path defaults to TRY_ALTERNATIVE
    diag_path = DenialDiagnosticReporter.generate_diagnostic(
        blocked_action="write_etc_hosts",
        denial_reason="Modifying system file /etc/hosts is forbidden.",
        reason_code=DenialReasonCodeEnum.UNAUTHORIZED_PATH,
        policy_rule_id="RULE-PATH-02",
    )
    assert diag_path.suggested_branch == ResolutionBranchEnum.TRY_ALTERNATIVE
    assert any("patch" in alt for alt in diag_path.allowed_alternatives)

    # 3. Isolation breach defaults to STOP_OPERATION
    diag_breach = DenialDiagnosticReporter.generate_diagnostic(
        blocked_action="ptrace_attach",
        denial_reason="Sandbox breakout attempt detected.",
        reason_code=DenialReasonCodeEnum.SANDBOX_ISOLATION_BREACH,
        policy_rule_id="RULE-SEC-CRIT",
    )
    assert diag_breach.suggested_branch == ResolutionBranchEnum.STOP_OPERATION


def test_four_way_state_machine_loop_breaker() -> None:
    """Test isomorphic retry loop breaking after repeated failures on same action."""
    sm = FourWayResolutionStateMachine(max_isomorphic_attempts=2)
    session_id = "sess-loop-01"

    diag = DenialDiagnosticReporter.generate_diagnostic(
        blocked_action="modify_root_cert",
        denial_reason="Root certificate modification forbidden.",
        reason_code=DenialReasonCodeEnum.POLICY_VIOLATION,
        policy_rule_id="RULE-ROOT-01",
    )

    # First attempt: TRY_ALTERNATIVE is permitted
    sm.register_denial(session_id, diag)
    branch1, _ = sm.evaluate_effective_branch(session_id, ResolutionBranchEnum.TRY_ALTERNATIVE)
    assert branch1 == ResolutionBranchEnum.TRY_ALTERNATIVE

    # Second attempt: still within limit
    sm.register_denial(session_id, diag)
    branch2, _ = sm.evaluate_effective_branch(session_id, ResolutionBranchEnum.TRY_ALTERNATIVE)
    assert branch2 == ResolutionBranchEnum.TRY_ALTERNATIVE

    # Third attempt: threshold exceeded (> 2) -> forced HANDOVER_TO_USER
    sm.register_denial(session_id, diag)
    branch3, reason3 = sm.evaluate_effective_branch(session_id, ResolutionBranchEnum.TRY_ALTERNATIVE)
    assert branch3 == ResolutionBranchEnum.HANDOVER_TO_USER
    assert "Loop breaker engaged" in reason3

    # Commit decision and verify history
    rec = sm.commit_resolution_decision(
        session_id=session_id,
        chosen_branch=ResolutionBranchEnum.HANDOVER_TO_USER,
        rationale="Automated loop break accepted",
    )
    assert rec.chosen_branch == ResolutionBranchEnum.HANDOVER_TO_USER
    assert len(sm.get_history(session_id)) == 1
    assert sm.get_active_denial(session_id) is None


def test_handover_deck_lifecycle() -> None:
    """Test staging, execution, and dismissal of human handover decks."""
    mgr = HandoverDeckManager()
    session_id = "sess-deck-01"

    # Stage card
    deck = mgr.stage_handover(
        session_id=session_id,
        task_description="Apply sensitive database migration",
        prepared_command="alembic upgrade head",
        parameters={"db": "prod_users", "revision": "head"},
        guidance_notes="Please confirm DB replica lag before releasing.",
    )
    assert deck.status == HandoverStatusEnum.STAGED
    assert len(mgr.list_staged_handovers(session_id)) == 1

    # User executes
    exec_deck = mgr.execute_handover(deck.handover_id)
    assert exec_deck is not None
    assert exec_deck.status == HandoverStatusEnum.EXECUTED_BY_USER
    assert exec_deck.executed_at is not None
    assert len(mgr.list_staged_handovers(session_id)) == 0

    # Stage and dismiss another
    deck2 = mgr.stage_handover(
        session_id=session_id,
        task_description="Delete old backup volume",
        prepared_command="rm -rf /volumes/backup_2025",
        parameters={},
        guidance_notes="Irreversible operation.",
    )
    dism_deck = mgr.dismiss_handover(deck2.handover_id)
    assert dism_deck is not None
    assert dism_deck.status == HandoverStatusEnum.DISMISSED_BY_USER


def test_facade_end_to_end_and_metrics() -> None:
    """Test facade coordinated reporting, evaluation, handover staging, and metrics."""
    facade = AutoReviewResolutionFacade()
    session_id = "sess-facade-01"

    # 1. Report denial
    diag = facade.report_and_register_denial(
        session_id=session_id,
        blocked_action="git_push_main",
        denial_reason="Direct push to main branch blocked by branch protection.",
        reason_code=DenialReasonCodeEnum.POLICY_VIOLATION,
        policy_rule_id="RULE-GIT-MAIN",
        context_data={"branch": "main"},
    )
    assert diag.blocked_action == "git_push_main"
    assert facade.get_active_denial(session_id) is not None

    # 2. Evaluate branch
    eff_branch, _ = facade.evaluate_branch(session_id, ResolutionBranchEnum.HANDOVER_TO_USER)
    assert eff_branch == ResolutionBranchEnum.HANDOVER_TO_USER

    # 3. Stage handover card
    deck = facade.stage_handover_deck(
        session_id=session_id,
        task_description="Create PR and push to feature branch instead",
        prepared_command="git checkout -b fix-auth && git push origin fix-auth",
        parameters={"branch": "fix-auth"},
        guidance_notes="Safe feature branch diversion.",
    )
    assert deck.status == HandoverStatusEnum.STAGED

    # 4. User executes card
    executed_deck = facade.execute_handover(deck.handover_id)
    assert executed_deck is not None
    assert executed_deck.status == HandoverStatusEnum.EXECUTED_BY_USER

    # 5. Commit decision
    rec = facade.commit_resolution(
        session_id=session_id,
        chosen_branch=ResolutionBranchEnum.HANDOVER_TO_USER,
        rationale="Handed over feature branch push to human.",
        handover_id=deck.handover_id,
    )
    assert rec.handover_id == deck.handover_id

    # 6. Verify metrics
    metrics = facade.get_metrics()
    assert metrics.total_denials_processed == 1
    assert metrics.branch_handover_count == 1
    assert metrics.handovers_executed_by_user == 1
    assert metrics.branch_stop_count == 0
