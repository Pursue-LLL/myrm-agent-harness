# ============================================================================
# Unit Tests: Dynamic Prompt Cache Breakeven Governor & Circuit Breaker (Item 166)
# ============================================================================

import pytest

from myrm_agent_harness.agent.context_management.cache_governor import (
    CacheRoiStatus,
    DynamicPromptCacheBreakevenGovernor,
    ModelPricingTier,
    TaskReuseKind,
)


def test_single_turn_qa_negative_roi_suppression() -> None:
    """Test single-turn QA triggering negative ROI circuit breaker suppression."""
    governor = DynamicPromptCacheBreakevenGovernor()
    session_id = "session-single-qa-1"

    decision = governor.evaluate_pre_flight_decision(
        model_name="claude-3-5-sonnet",
        task_kind=TaskReuseKind.SINGLE_TURN_QA,
        estimated_tokens=5000,
        session_id=session_id,
    )

    # Must suppress cache to avoid 25% write penalty on one-off call
    assert decision.should_suppress_cache is True
    assert decision.roi_status == CacheRoiStatus.NEGATIVE_SUPPRESSED
    assert decision.analysis.expected_turns == 1
    assert decision.analysis.min_reuse_turns == 2
    assert pytest.approx(decision.analysis.breakeven_ratio, rel=1e-3) == 0.2778
    assert "事前自适应熔断" in decision.reason

    # Verify ledger recorded suppression event
    ledger = governor.get_session_ledger(session_id)
    assert ledger is not None
    assert ledger.suppressed_events_count == 1


def test_multi_turn_deep_workflow_positive_roi_qualification() -> None:
    """Test multi-turn task qualifying for positive ROI cache injection."""
    governor = DynamicPromptCacheBreakevenGovernor()

    decision = governor.evaluate_pre_flight_decision(
        model_name="claude-3-5-sonnet",
        task_kind=TaskReuseKind.MULTI_TURN_ITERATION,
        estimated_tokens=10000,
    )

    assert decision.should_suppress_cache is False
    assert decision.roi_status == CacheRoiStatus.ROI_POSITIVE
    assert decision.analysis.expected_turns == 5
    assert decision.analysis.predicted_net_roi_factor > 0
    assert "预计可对冲" in decision.reason


def test_zero_write_penalty_model_neutral_qualification() -> None:
    """Test model with 1.0x write multiplier (zero penalty) safely allowed."""
    governor = DynamicPromptCacheBreakevenGovernor()

    decision = governor.evaluate_pre_flight_decision(
        model_name="qwen-max",
        task_kind=TaskReuseKind.SINGLE_TURN_QA,
        estimated_tokens=3000,
    )

    assert decision.should_suppress_cache is False
    assert decision.roi_status == CacheRoiStatus.NEUTRAL_NO_PREMIUM
    assert decision.analysis.breakeven_ratio == 0.0


def test_session_net_roi_ledger_and_global_audit() -> None:
    """Test financial ledger tracking of gross savings, write penalties, and net USD ROI."""
    governor = DynamicPromptCacheBreakevenGovernor()
    session_id = "session-audit-123"
    model = "claude-3-5-sonnet"  # base=3e-6, write=1.25, read=0.10

    # Turn 1: Cache creation (write penalty)
    usage_turn1 = {
        "prompt_tokens": 10000,
        "prompt_tokens_details": {
            "cached_tokens": 0,
            "cache_creation_input_tokens": 10000,
        },
    }
    entry1 = governor.record_session_usage(session_id, usage_turn1, model)
    # penalty = 10000 * (3e-6 * 0.25) = 10000 * 0.75e-6 = 0.0075 USD
    assert entry1.write_penalty_usd == 0.0075
    assert entry1.gross_savings_usd == 0.0
    assert entry1.net_savings_usd == -0.0075  # Negative ROI on initial write turn

    # Turn 2: Cache hit (read savings recoups penalty)
    usage_turn2 = {
        "prompt_tokens": 10000,
        "prompt_tokens_details": {
            "cached_tokens": 10000,
            "cache_creation_input_tokens": 0,
        },
    }
    entry2 = governor.record_session_usage(session_id, usage_turn2, model)
    # savings = 10000 * (3e-6 * 0.90) = 10000 * 2.7e-6 = 0.027 USD
    # net = 0.027 - 0.0075 = +0.0195 USD
    assert entry2.gross_savings_usd == 0.027
    assert entry2.write_penalty_usd == 0.0075
    assert entry2.net_savings_usd == 0.0195  # Positive net ROI!

    # Global summary check
    summary = governor.get_global_audit_summary()
    assert summary["active_sessions_tracked"] == 1
    assert summary["total_prompt_tokens"] == 20000
    assert summary["total_cached_tokens"] == 10000
    assert summary["total_cache_creation_tokens"] == 10000
    assert summary["total_net_savings_usd"] == 0.0195


def test_custom_turns_override_and_custom_pricing_registration() -> None:
    """Test explicit custom turn override and dynamic custom pricing registration."""
    governor = DynamicPromptCacheBreakevenGovernor()

    # Register custom enterprise model with high 1.5x write premium
    custom_tier = ModelPricingTier(
        model_name="custom-enterprise-llm",
        input_cost_per_token=10e-6,
        cache_write_multiplier=1.50,
        cache_read_multiplier=0.20,
    )
    governor.register_model_pricing(custom_tier)

    # 1. Custom turns = 1 should suppress (breakeven ratio = 0.5 / 0.8 = 62.5%)
    d1 = governor.evaluate_pre_flight_decision(
        model_name="custom-enterprise-llm",
        task_kind=TaskReuseKind.MULTI_TURN_ITERATION,
        estimated_tokens=5000,
        custom_turns=1,
    )
    assert d1.should_suppress_cache is True
    assert pytest.approx(d1.analysis.breakeven_ratio, rel=1e-3) == 0.625

    # 2. Custom turns = 4 should qualify
    d2 = governor.evaluate_pre_flight_decision(
        model_name="custom-enterprise-llm",
        task_kind=TaskReuseKind.SINGLE_TURN_QA,
        estimated_tokens=5000,
        custom_turns=4,
    )
    assert d2.should_suppress_cache is False
    assert d2.roi_status == CacheRoiStatus.ROI_POSITIVE
