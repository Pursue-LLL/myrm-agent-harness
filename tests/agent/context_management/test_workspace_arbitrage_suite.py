"""Comprehensive tests for WorkWithChatUnifiedWorkspaceDeckAndMultiModelCostArbitrageSuite.

[INPUT]
- workspace_arbitrage package contracts and implementations.

[OUTPUT]
- Deterministic verification of inline deck widgets, complexity-based arbitrage routing,
  zero-loss dynamic promotion, dual persona prompt modification, anti-downgrade fingerprinting,
  budget watermark fusing, and unified suite orchestration.

[POS]
- Sub-package: tests.agent.context_management
- Module: test_workspace_arbitrage_suite.py
"""

import pytest
from myrm_agent_harness.agent.context_management.workspace_arbitrage import (
    AntiDowngradeBudgetGuard,
    BudgetWatermarkLevel,
    BudgetWatermarkStatus,
    ComplexityHeuristicAnalyzer,
    CostPerformanceArbitrageRouter,
    DeckActionResult,
    DeckInteractionEvent,
    DeckWidgetSpec,
    DeckWidgetState,
    DeckWidgetType,
    DualPersonaSwitcher,
    InlineDeckManager,
    ModelArbitrageTier,
    PersonaMode,
    RoutingDecision,
    WorkWithChatUnifiedWorkspaceDeckAndMultiModelCostArbitrageSuite,
    WorkspaceArbitrageConfig,
)


def test_inline_deck_manager_lifecycle_and_interaction() -> None:
    """Verifies registration, state transitions, and context projections of inline widgets."""
    manager = InlineDeckManager()

    approval_widget = DeckWidgetSpec(
        widget_id="w-approval-1",
        message_id="msg-101",
        widget_type=DeckWidgetType.STEP_APPROVAL,
        title="Approve database migration schema",
        initial_payload={"sql": "ALTER TABLE users ADD COLUMN tier TEXT;"},
    )
    diff_widget = DeckWidgetSpec(
        widget_id="w-diff-2",
        message_id="msg-101",
        widget_type=DeckWidgetType.DIFF_VIEW,
        title="Refactor auth middleware diff",
        initial_payload={"diff": "--- a/auth.py\n+++ b/auth.py\n@@ ... @@"},
    )
    slider_widget = DeckWidgetSpec(
        widget_id="w-slider-3",
        message_id="msg-102",
        widget_type=DeckWidgetType.PARAM_SLIDER,
        title="Max Concurrency Limit",
        initial_payload={"value": "10"},
    )
    terminal_widget = DeckWidgetSpec(
        widget_id="w-term-4",
        message_id="msg-102",
        widget_type=DeckWidgetType.MICRO_TERMINAL,
        title="Run sandbox verification suite",
        initial_payload={"command": "pytest -q tests/sanity.py"},
    )

    manager.register_widget(approval_widget)
    manager.register_widget(diff_widget)
    manager.register_widget(slider_widget)
    manager.register_widget(terminal_widget)

    assert len(manager.list_all_widgets()) == 4
    assert len(manager.list_widgets_for_message("msg-101")) == 2
    assert len(manager.list_widgets_for_message("msg-102")) == 2

    # 1. Test step approval
    res1 = manager.handle_interaction(
        DeckInteractionEvent(
            widget_id="w-approval-1",
            action_name="approve",
            parameters={"signer": "admin"},
        )
    )
    assert res1.success is True
    assert res1.new_state == DeckWidgetState.APPROVED
    assert manager.get_widget("w-approval-1") is not None
    assert manager.get_widget("w-approval-1").state == DeckWidgetState.APPROVED

    # 2. Test diff rejection
    res2 = manager.handle_interaction(
        DeckInteractionEvent(
            widget_id="w-diff-2",
            action_name="discard",
        )
    )
    assert res2.success is True
    assert res2.new_state == DeckWidgetState.REJECTED

    # 3. Test terminal execution
    res3 = manager.handle_interaction(
        DeckInteractionEvent(
            widget_id="w-term-4",
            action_name="execute",
        )
    )
    assert res3.success is True
    assert res3.new_state == DeckWidgetState.EXECUTED

    # 4. Context projection rendering
    summary = manager.render_context_summary(max_items=3)
    assert "[INLINE_WORK_DECK_STATUS]" in summary
    assert "w-term-4" in summary
    assert "executed" in summary


def test_complexity_heuristic_analyzer() -> None:
    """Verifies multi-dimensional scoring of prompts across conversational vs reasoning."""
    analyzer = ComplexityHeuristicAnalyzer()

    simple_prompt = "Hello, can you help me check if today is Monday?"
    score_simple = analyzer.analyze(simple_prompt)
    assert score_simple.composite_score < 0.40
    assert score_simple.is_code_heavy is False

    complex_code_prompt = (
        "def reconcile_memory_drift(session_id: str) -> None:\n"
        "    # Please refactor this architecture to eliminate deadlocks and optimize complexity step by step\n"
        "    pass\n"
    )
    score_complex = analyzer.analyze(complex_code_prompt)
    assert score_complex.composite_score >= 0.55
    assert score_complex.is_code_heavy is True
    assert score_complex.is_multi_step_planning is True
    assert len(score_complex.reasons) >= 2


def test_cost_performance_arbitrage_router_and_dynamic_promotion() -> None:
    """Verifies economic tier routing, forced overrides, and zero-loss dynamic promotion."""
    config = WorkspaceArbitrageConfig(
        l1_default_model="deepseek-chat-fast",
        l2_default_model="claude-3-7-sonnet",
        complexity_threshold_for_l2=0.55,
    )
    router = CostPerformanceArbitrageRouter(config)

    # 1. Simple query routes to economic L1 tier
    decision_l1 = router.route_prompt("Summarize the meeting notes briefly.", "session-1")
    assert decision_l1.selected_tier == ModelArbitrageTier.L1_FAST_LOCAL
    assert decision_l1.target_model_name == "deepseek-chat-fast"

    # 2. Complex architectural prompt routes to flagship L2 tier
    decision_l2 = router.route_prompt(
        "Please architect a distributed consensus engine with cryptographic reconciliation step by step.",
        "session-1",
    )
    assert decision_l2.selected_tier == ModelArbitrageTier.L2_FLAGSHIP_REASONING
    assert decision_l2.target_model_name == "claude-3-7-sonnet"

    # 3. Forced override
    decision_forced = router.route_prompt(
        "Complex code refactor class Foo:",
        "session-1",
        forced_tier=ModelArbitrageTier.L1_FAST_LOCAL,
    )
    assert decision_forced.selected_tier == ModelArbitrageTier.L1_FAST_LOCAL

    # 4. Dynamic promotion after tool execution difficulties
    promoted = router.evaluate_promotion(
        current_decision=decision_l1,
        consecutive_tool_failures=2,
    )
    assert promoted.selected_tier == ModelArbitrageTier.L2_FLAGSHIP_REASONING
    assert promoted.promoted_from_l1 is True
    assert "Dynamically promoted" in promoted.decision_reason

    # 5. Financial savings tracking
    savings = router.record_arbitrage_savings(
        session_id="session-1",
        total_tokens=10000,
        actual_tier=ModelArbitrageTier.L1_FAST_LOCAL,
    )
    assert savings.saved_usd > 0.0
    assert savings.saving_ratio >= 0.80

    summary = router.get_session_savings_summary("session-1")
    assert summary["total_saved_usd"] > 0.0
    assert summary["overall_saving_ratio"] >= 0.80


def test_dual_persona_switcher() -> None:
    """Verifies demeanor modification and generation parameter recommendations."""
    switcher = DualPersonaSwitcher()

    base = "You are a helpful software assistant."
    prof_prompt = switcher.modify_system_prompt(base, mode=PersonaMode.PROFESSIONAL, warmth_level=0.2)
    assert "[PERSONA_DIRECTIVE: PROFESSIONAL_MODE]" in prof_prompt
    assert "[WARMTH_LEVEL: 0.20]" in prof_prompt

    comp_prompt = switcher.modify_system_prompt(base, mode=PersonaMode.COMPANION, warmth_level=0.85)
    assert "[PERSONA_DIRECTIVE: COMPANION_MODE]" in comp_prompt
    assert "[WARMTH_LEVEL: 0.85]" in comp_prompt

    temp_prof, top_p_prof = switcher.recommend_generation_params(PersonaMode.PROFESSIONAL)
    assert temp_prof <= 0.30

    temp_comp, top_p_comp = switcher.recommend_generation_params(PersonaMode.COMPANION)
    assert temp_comp >= 0.70


def test_anti_downgrade_budget_guard() -> None:
    """Verifies model fingerprint drift detection and budget watermark fusing."""
    config = WorkspaceArbitrageConfig(
        default_session_budget_usd=1.00,
        soft_budget_warning_ratio=0.80,
        hard_budget_fuse_ratio=1.00,
    )
    guard = AntiDowngradeBudgetGuard(config)

    # 1. Normal baseline call
    p1 = guard.record_model_call(
        model_name="claude-3-7-sonnet",
        system_fingerprint="fp_20261001",
        latency_ms=1200.0,
        output_token_count=500,
    )
    assert p1.detected_drift is False

    # 2. Call with changed fingerprint AND abnormal latency spike (3x)
    p2 = guard.record_model_call(
        model_name="claude-3-7-sonnet",
        system_fingerprint="fp_downgraded_20261009",
        latency_ms=4000.0,
        output_token_count=500,
    )
    assert p2.detected_drift is True

    # 3. Budget tracking: normal -> soft warning (80%) -> hard fuse (100%)
    status_init = guard.track_spending("session-budget-test", 0.50)
    assert status_init.watermark_level == BudgetWatermarkLevel.NORMAL
    assert status_init.enforce_fallback_to_local is False

    status_warn = guard.track_spending("session-budget-test", 0.35)
    assert status_warn.watermark_level == BudgetWatermarkLevel.SOFT_WARNING_80
    assert status_warn.consumed_usd == 0.85
    assert status_warn.enforce_fallback_to_local is False

    status_fuse = guard.track_spending("session-budget-test", 0.20)
    assert status_fuse.watermark_level == BudgetWatermarkLevel.HARD_FUSED_100
    assert status_fuse.enforce_fallback_to_local is True


def test_workspace_arbitrage_suite_end_to_end() -> None:
    """Verifies end-to-end orchestration of unified deck, arbitrage, and guards."""
    suite = WorkWithChatUnifiedWorkspaceDeckAndMultiModelCostArbitrageSuite()

    # 1. Register inline widget
    suite.register_widget(
        DeckWidgetSpec(
            widget_id="w-patch-1",
            message_id="m-init",
            widget_type=DeckWidgetType.DIFF_VIEW,
            title="Auto-generated migration patch",
        )
    )

    # 2. Prepare turn execution
    routing, modified_prompt, sampling, deck_ctx = suite.prepare_turn_execution(
        session_id="s-e2e",
        prompt="Explain this query structure simply.",
        base_system_prompt="Base system instructions.",
        persona_mode=PersonaMode.COMPANION,
        warmth_level=0.9,
    )
    assert routing.selected_tier == ModelArbitrageTier.L1_FAST_LOCAL
    assert "[PERSONA_DIRECTIVE: COMPANION_MODE]" in modified_prompt
    assert sampling[0] >= 0.70
    assert "w-patch-1" in deck_ctx

    # 3. Record turn outcome
    savings, fp, budget = suite.record_turn_outcome(
        session_id="s-e2e",
        decision=routing,
        total_tokens=2500,
        system_fingerprint="fp_stable",
        latency_ms=800.0,
    )
    assert savings.saved_usd > 0.0
    assert fp.detected_drift is False
    assert budget.watermark_level == BudgetWatermarkLevel.NORMAL

    # 4. Handle widget action
    act_res = suite.handle_widget_action(
        DeckInteractionEvent(widget_id="w-patch-1", action_name="apply_diff")
    )
    assert act_res.success is True
    assert act_res.new_state == DeckWidgetState.EXECUTED

    # 5. Enforce budget fuse fallback
    suite.budget_guard.set_session_limit("s-e2e", 0.001)  # tiny budget limit
    suite.budget_guard.track_spending("s-e2e", 0.01)  # exceed limit
    routing_fused, _, _, _ = suite.prepare_turn_execution(
        session_id="s-e2e",
        prompt="Deep architectural refactoring needed.",
        base_system_prompt="Base prompt",
    )
    assert routing_fused.target_model_name == suite._config.local_fallback_model
    assert "hard budget limit reached" in routing_fused.decision_reason
