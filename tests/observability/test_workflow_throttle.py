"""
Tests for massive workflow token burn rate calculation and tiered budget safety governor.
"""

from myrm_agent_harness.observability.workflow_throttle.burn_governor import (
    WorkflowTokenBurnGovernor,
)
from myrm_agent_harness.observability.workflow_throttle.models import (
    BudgetLadderTier,
    BudgetLadderVerdict,
    WorkflowTokenBurnSample,
)


def test_burn_rate_sliding_window_calculation() -> None:
    governor = WorkflowTokenBurnGovernor(window_size=5)
    workflow_id = "wf-batch-1024"

    # Checkpoint 0 at t=100.0s, tokens=0, cost=0.0
    r1_tokens, r1_cost = governor.record_checkpoint(workflow_id, 0, 0.0, timestamp=100.0)
    assert r1_tokens == 0.0
    assert r1_cost == 0.0

    # Checkpoint 1 at t=102.0s (+2s), tokens=2000 (+2000), cost=0.04
    r2_tokens, r2_cost = governor.record_checkpoint(workflow_id, 2000, 0.04, timestamp=102.0)
    # Rate: 2000 tokens / 2s = 1000 tokens/sec
    # Cost per hour: (0.04 / 2) * 3600 = 72.0 USD/hour
    assert abs(r2_tokens - 1000.0) < 0.01
    assert abs(r2_cost - 72.0) < 0.01

    # Checkpoint 2 at t=105.0s (+3s), tokens=6500 (+4500), cost=0.10
    r3_tokens, r3_cost = governor.record_checkpoint(workflow_id, 6500, 0.10, timestamp=105.0)
    # Between oldest (t=100) and now (t=105), dt=5s, d_tokens=6500, d_cost=0.10
    # Rate: 6500 / 5 = 1300 tokens/sec
    # Cost per hour: (0.10 / 5) * 3600 = 72.0 USD/hour
    assert abs(r3_tokens - 1300.0) < 0.01
    assert abs(r3_cost - 72.0) < 0.01


def test_budget_ladder_tier_transitions() -> None:
    governor = WorkflowTokenBurnGovernor()
    workflow_id = "wf-crawler-88"
    budget_tokens = 100_000
    budget_cost = 5.0

    # 1. Under 50% (< 50,000 tokens) -> NORMAL
    v1 = governor.evaluate_budget(
        workflow_id=workflow_id,
        cumulative_tokens=30_000,
        budget_tokens=budget_tokens,
        cumulative_cost_usd=1.0,
        budget_cost_usd=budget_cost,
    )
    assert v1.tier == BudgetLadderTier.NORMAL
    assert v1.is_throttled is False
    assert v1.is_suspended is False
    assert v1.throttle_factor == 1.0
    assert v1.recommended_model_tier == "primary"

    # 2. 50% to 80% (60,000 tokens) -> TIER1_NOTICE
    v2 = governor.evaluate_budget(
        workflow_id=workflow_id,
        cumulative_tokens=60_000,
        budget_tokens=budget_tokens,
        cumulative_cost_usd=2.5,
        budget_cost_usd=budget_cost,
    )
    assert v2.tier == BudgetLadderTier.TIER1_NOTICE
    assert v2.is_throttled is False
    assert v2.is_suspended is False
    assert v2.throttle_factor == 1.0
    assert v2.recommended_model_tier == "primary"

    # 3. 80% to 100% (85,000 tokens) -> TIER2_DEGRADED
    v3 = governor.evaluate_budget(
        workflow_id=workflow_id,
        cumulative_tokens=85_000,
        budget_tokens=budget_tokens,
        cumulative_cost_usd=4.0,
        budget_cost_usd=budget_cost,
    )
    assert v3.tier == BudgetLadderTier.TIER2_DEGRADED
    assert v3.is_throttled is True
    assert v3.is_suspended is False
    assert v3.throttle_factor == 0.5
    assert v3.recommended_model_tier == "economy"

    # 4. >= 100% (105,000 tokens) -> TIER3_SUSPENDED
    v4 = governor.evaluate_budget(
        workflow_id=workflow_id,
        cumulative_tokens=105_000,
        budget_tokens=budget_tokens,
        cumulative_cost_usd=5.25,
        budget_cost_usd=budget_cost,
    )
    assert v4.tier == BudgetLadderTier.TIER3_SUSPENDED
    assert v4.is_throttled is True
    assert v4.is_suspended is True
    assert v4.throttle_factor == 0.0
    assert v4.recommended_model_tier == "halted"


def test_models_serialization() -> None:
    sample = WorkflowTokenBurnSample(
        timestamp=1700000000.123,
        tokens_per_sec=1420.5,
        cost_per_hour_usd=45.67,
        cumulative_prompt_tokens=40000,
        cumulative_completion_tokens=10000,
        cumulative_cost_usd=1.25,
        active_agent_count=64,
        agent_burn_distribution={"agent-1": 15000, "agent-2": 12000},
    )

    data = sample.to_dict()
    assert data["total_cumulative_tokens"] == 50000
    assert data["active_agent_count"] == 64
    assert data["tokens_per_sec"] == 1420.5
    assert "agent-1" in data["agent_burn_distribution"]
