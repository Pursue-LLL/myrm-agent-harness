"""Unit tests for Token Economics Telemetry and Cost Regression Detector."""

import pytest

from myrm_agent_harness.observability.economics import (
    CostRegressionDetector,
    SpurtSeverity,
    TokenCostSpurtWarning,
    TokenEconomicsAuditor,
    TokenEfficiencyScore,
    TokenStepMetrics,
)


def test_token_step_metrics_properties():
    """Test TokenStepMetrics uncached calculations and cache hit ratio."""
    step = TokenStepMetrics(
        step_id="step_1",
        step_index=0,
        prompt_tokens=10_000,
        completion_tokens=500,
        cached_prompt_tokens=8_000,
        tool_name="bash_exec",
    )
    assert step.total_tokens == 10_500
    assert step.uncached_prompt_tokens == 2_000
    assert step.cache_hit_ratio == 0.80

    zero_step = TokenStepMetrics(
        step_id="step_zero",
        step_index=1,
        prompt_tokens=0,
        completion_tokens=0,
    )
    assert zero_step.cache_hit_ratio == 0.0


def test_token_economics_auditor_grading_and_costs():
    """Test TokenEconomicsAuditor cost estimation and efficiency grading."""
    auditor = TokenEconomicsAuditor(
        price_per_million_uncached=2.5,
        price_per_million_cached=0.5,
        price_per_million_completion=10.0,
    )

    # 1. High cache hit step (80% cached)
    s1 = TokenStepMetrics(
        step_id="s1",
        step_index=0,
        prompt_tokens=100_000,
        completion_tokens=2_000,
        cached_prompt_tokens=80_000,
    )
    cost1 = auditor.estimate_step_cost(s1)
    # uncached: 20k / 1M * 2.5 = 0.05
    # cached: 80k / 1M * 0.5 = 0.04
    # completion: 2k / 1M * 10.0 = 0.02
    # total = 0.11
    assert round(cost1, 4) == 0.1100

    score_high = auditor.evaluate_steps([s1])
    assert score_high.overall_cache_hit_ratio == 0.8
    assert score_high.efficiency_grade == "A"
    assert "Excellent prompt cache utilization" in score_high.recommendations[0]

    # 2. Low cache hit steps (0% cached)
    s2 = TokenStepMetrics(
        step_id="s2",
        step_index=1,
        prompt_tokens=50_000,
        completion_tokens=1_000,
        cached_prompt_tokens=0,
    )
    score_low = auditor.evaluate_steps([s2])
    assert score_low.overall_cache_hit_ratio == 0.0
    assert score_low.efficiency_grade == "F"


def test_cost_regression_detector_spurt_and_cache_drop():
    """Test CostRegressionDetector identifying sudden token surges and cache drops."""
    detector = CostRegressionDetector(
        spurt_threshold_ratio=3.0,
        min_spurt_token_jump=5_000,
        cache_drop_threshold=0.50,
    )

    steps = [
        TokenStepMetrics(
            step_id="s0",
            step_index=0,
            prompt_tokens=2_000,
            completion_tokens=200,
            cached_prompt_tokens=1_800,  # 90% cache
        ),
        TokenStepMetrics(
            step_id="s1",
            step_index=1,
            prompt_tokens=2_500,
            completion_tokens=200,
            cached_prompt_tokens=2_000,  # 80% cache
        ),
        TokenStepMetrics(
            step_id="s2",
            step_index=2,
            prompt_tokens=30_000,  # Token spurt jump (30k vs ~2.3k baseline)
            completion_tokens=1_000,
            cached_prompt_tokens=1_000,  # Sharp cache drop from 80% to 3.3%
            tool_name="web_fetch",
        ),
    ]

    warnings = detector.inspect_step_stream(steps, session_id="sess_regression_test")
    assert len(warnings) >= 1

    spurt_warnings = [w for w in warnings if "token cost spurt" in w.reason]
    assert len(spurt_warnings) == 1
    assert spurt_warnings[0].step_index == 2
    assert spurt_warnings[0].actual_tokens == 31_000
    assert spurt_warnings[0].offending_tool == "web_fetch"

    cache_warnings = [w for w in warnings if "Sharp prompt cache drop" in w.reason]
    assert len(cache_warnings) == 1
    assert cache_warnings[0].step_index == 2
