"""
[INPUT]: DelegationBillingTracker, DelegationAuthMode, DelegationUsageRecord.
[OUTPUT]: Pytest test cases verifying dual-shape adaptation, subscription vs api_key divergence, savings calculations, and summary metrics.
[POS]: myrm-agent-harness/tests/observability/test_delegation_billing.py
"""

import pytest
from myrm_agent_harness.observability.delegation_billing import (
    DelegationAuthMode,
    DelegationBillingTracker,
    DelegationUsageRecord,
)


@pytest.fixture
def tracker() -> DelegationBillingTracker:
    t = DelegationBillingTracker()
    t.reset()
    return t


def test_subscription_delegation_zero_billed_and_calculates_savings(tracker: DelegationBillingTracker) -> None:
    record: DelegationUsageRecord = tracker.record_delegation(
        session_id="session-sub-1",
        source="delegate:claude",
        input_tokens=1000,
        output_tokens=500,
        auth_mode=DelegationAuthMode.SUBSCRIPTION,
    )

    assert record.session_id == "session-sub-1"
    assert record.source == "delegate:claude"
    assert record.total_tokens == 1500
    assert record.auth_mode == DelegationAuthMode.SUBSCRIPTION
    assert record.billable is False
    assert record.billed_cost_usd == 0.0
    # 1000 * 0.000003 ($0.003) + 500 * 0.000015 ($0.0075) = $0.0105
    assert record.estimated_savings_usd == pytest.approx(0.0105, abs=1e-5)


def test_api_key_delegation_is_billable(tracker: DelegationBillingTracker) -> None:
    record: DelegationUsageRecord = tracker.record_delegation(
        session_id="session-api-1",
        source="delegate:codex",
        input_tokens=2000,
        output_tokens=1000,
        auth_mode=DelegationAuthMode.API_KEY,
    )

    assert record.auth_mode == DelegationAuthMode.API_KEY
    assert record.billable is True
    assert record.estimated_savings_usd == 0.0
    # 2000 * 0.000003 ($0.006) + 1000 * 0.000015 ($0.015) = $0.021
    assert record.billed_cost_usd == pytest.approx(0.021, abs=1e-5)


def test_dual_shape_adaptation(tracker: DelegationBillingTracker) -> None:
    # Shape A: Server flat payload with input_tokens / output_tokens
    rec_flat = tracker.adapt_raw_event(
        session_id="session-flat",
        raw_data={
            "source": "delegate:claude",
            "input_tokens": 1500,
            "output_tokens": 500,
            "auth_mode": "subscription",
            "billable": False,
        },
    )
    assert rec_flat.input_tokens == 1500
    assert rec_flat.output_tokens == 500
    assert rec_flat.auth_mode == DelegationAuthMode.SUBSCRIPTION
    assert rec_flat.billable is False

    # Shape B: Nested usage dict with prompt_tokens / completion_tokens
    rec_nested = tracker.adapt_raw_event(
        session_id="session-nested",
        raw_data={
            "source": "invoke_acp:gpt4o",
            "usage": {
                "prompt_tokens": 800,
                "completion_tokens": 200,
            },
            "auth_mode": "api_key",
            "cost_usd": 0.045,
        },
    )
    assert rec_nested.input_tokens == 800
    assert rec_nested.output_tokens == 200
    assert rec_nested.auth_mode == DelegationAuthMode.API_KEY
    assert rec_nested.billable is True
    assert rec_nested.billed_cost_usd == pytest.approx(0.045, abs=1e-5)


def test_summary_and_reset(tracker: DelegationBillingTracker) -> None:
    # Record 1 subscription run
    tracker.record_delegation("s1", "delegate:claude", 1000, 500, DelegationAuthMode.SUBSCRIPTION)
    # Record 1 api_key run
    tracker.record_delegation("s2", "delegate:claude", 2000, 1000, DelegationAuthMode.API_KEY)

    summary = tracker.get_summary()
    assert summary.total_delegations == 2
    assert summary.subscription_calls_count == 1
    assert summary.api_key_calls_count == 1
    assert summary.total_subscription_tokens == 1500
    assert summary.total_api_key_tokens == 3000
    assert summary.total_estimated_savings_usd > 0.0
    assert summary.total_billed_cost_usd > 0.0
    assert len(summary.sources) == 1
    assert summary.sources[0].source == "delegate:claude"

    tracker.reset()
    empty_summary = tracker.get_summary()
    assert empty_summary.total_delegations == 0
    assert len(empty_summary.sources) == 0
