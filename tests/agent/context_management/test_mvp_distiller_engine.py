"""Unit tests for Complex Project MVP Scope Distiller and Stepwise Guide Suite (Item 214).

[INPUT]
- ComplexProjectMvpDistillerEngine, MvpDistillerConfig.
- Simulated project requests with varying complexity scopes.

[OUTPUT]
- Deterministic verification of complexity detection, staged MVP roadmap generation,
- and stepwise execution state machine handoffs.

[POS]
- Verifies proactive requirement convergence, lean MVP phase 1 extraction, and zero context bloating.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management.mvp_distiller import (
    ComplexProjectMvpDistillerEngine,
    MvpDistillerConfig,
    MvpPhaseLifecycleState,
    ProjectComplexityLevel,
)


def test_low_complexity_requirement_passthrough() -> None:
    """Verifies that simple, single-module requirements pass through without unnecessary intervention."""
    engine = ComplexProjectMvpDistillerEngine()
    simple_prompt = "请帮我写一个简单的个人作品展示网页，使用 React 渲染卡片。"

    outcome = engine.evaluate_requirement(simple_prompt)
    assert outcome.complexity_level in (ProjectComplexityLevel.LOW, ProjectComplexityLevel.MEDIUM)
    assert outcome.intervention_needed is False
    assert outcome.distillation_prompt_nudge == ""
    assert outcome.summary_card_markdown == ""
    assert outcome.evaluation_duration_ms > 0.0


def test_high_complexity_mvp_distillation_and_prompt_nudge() -> None:
    """Verifies that multi-domain bloated requirements trigger HIGH_COMPLEXITY_RISK and lean MVP extraction."""
    engine = ComplexProjectMvpDistillerEngine(
        config=MvpDistillerConfig(max_mvp_core_modules=3, high_risk_module_threshold=4)
    )
    bloated_prompt = (
        "我想做完整的生鲜电商平台：需要用户登录注册、SQLite 数据库持久化、商品列表详情首页展示、"
        "集成微信支付与 Stripe 结算、订单退款发货管理、以及运营管理后台仪表盘和全文检索通知。"
    )

    outcome = engine.evaluate_requirement(bloated_prompt)
    assert outcome.complexity_level == ProjectComplexityLevel.HIGH_COMPLEXITY_RISK
    assert outcome.intervention_needed is True
    assert len(outcome.detected_modules) >= 4

    # Verify Phase 1 MVP is strictly constrained to core modules (<= 3)
    assert len(outcome.phased_plans) >= 2
    phase_1 = outcome.phased_plans[0]
    assert phase_1.phase_index == 1
    assert len(phase_1.target_modules) <= 3
    assert "Phase 1: Core MVP Architecture" in phase_1.phase_name

    # Verify prompt nudge generation
    assert "<mvp_scope_distillation status='active'>" in outcome.distillation_prompt_nudge
    assert "Adopt Stepwise MVP Strategy" in outcome.distillation_prompt_nudge

    # Verify user-facing summary card markdown
    assert "### 🎯 项目需求主动收敛与 MVP 渐进开发建议" in outcome.summary_card_markdown
    assert "Phase 1: Core MVP" in outcome.summary_card_markdown


def test_stepwise_execution_state_machine_and_lean_handoff() -> None:
    """Verifies state machine transitions across proposed, active, verified, and clean context handoffs."""
    engine = ComplexProjectMvpDistillerEngine()
    session_id = "session_mvp_proj_001"

    prompt = "帮我做一个商城：带用户登录、数据库ORM、首页UI、Stripe支付、管理后台。"
    outcome = engine.evaluate_requirement(prompt)

    # Initially IDLE
    assert engine.get_session_state(session_id) == MvpPhaseLifecycleState.IDLE

    # Propose plan
    engine.propose_plan(session_id, outcome)
    assert engine.get_session_state(session_id) == MvpPhaseLifecycleState.PROPOSED

    # Accept & start Phase 1
    plan_1 = engine.accept_and_start_phase(session_id, phase_index=1)
    assert plan_1 is not None
    assert plan_1.phase_index == 1
    assert engine.get_session_state(session_id) == MvpPhaseLifecycleState.PHASE_1_ACTIVE

    # Verify Phase 1
    verified = engine.verify_phase(
        session_id=session_id,
        phase_index=1,
        verification_notes="SQLite schema and basic UI routes tested successfully.",
    )
    assert verified is True
    assert engine.get_session_state(session_id) == MvpPhaseLifecycleState.PHASE_1_VERIFIED

    # Generate lean handoff context (carries forward only contracts, not conversational bloat)
    contracts = "API /api/v1/items, Schema: Item(id, name, price)"
    handoff_ctx = engine.generate_phase_handoff_context(session_id, contracts)
    assert "[Phase 1 Handoff Contract - Verified]" in handoff_ctx
    assert "SQLite schema and basic UI routes tested successfully." in handoff_ctx
    assert "API /api/v1/items" in handoff_ctx

    # Start Phase 2
    plan_2 = engine.accept_and_start_phase(session_id, phase_index=2)
    assert plan_2 is not None
    assert plan_2.phase_index == 2
    assert engine.get_session_state(session_id) == MvpPhaseLifecycleState.PHASE_NEXT_READY

    # Verify last phase -> ALL_COMPLETED
    last_phase_idx = outcome.phased_plans[-1].phase_index
    engine.verify_phase(session_id, last_phase_idx, "Full integration verified.")
    assert engine.get_session_state(session_id) == MvpPhaseLifecycleState.ALL_COMPLETED

    # Session cleanup
    engine.clear_session(session_id)
    assert engine.get_session_state(session_id) == MvpPhaseLifecycleState.IDLE
