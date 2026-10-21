"""Unit tests for TokenUsage and TokenTracker Prompt Cache economic extensions.

[INPUT]
- myrm_agent_harness.utils.token_economics.tracker::TokenUsage
- myrm_agent_harness.utils.token_economics.tracker::TokenTracker

[OUTPUT]
- test_token_usage_cache_hit_rate: Validate cache_hit_rate property
- test_token_usage_to_economic_dict: Validate to_economic_dict and eligibility gates
- test_token_tracker_record_economic_event: Validate pending events contain cache economics
- test_token_tracker_to_dict_economics: Validate TokenTracker.to_dict contains cache metrics

[POS]
Unit test suite verifying prompt cache hit rate, net savings formatting, and threshold gating.
"""

from myrm_agent_harness.utils.token_economics.tracker import TokenTracker, TokenUsage


def test_token_usage_cache_hit_rate() -> None:
    """Test cache_hit_rate calculation across various input ratios."""
    # Zero prompt tokens
    empty = TokenUsage()
    assert empty.cache_hit_rate == 0.0

    # Partial cache hit
    usage = TokenUsage(prompt_tokens=10000, cached_tokens=8500)
    assert usage.cache_hit_rate == 0.85

    # Full cache hit
    full = TokenUsage(prompt_tokens=5000, cached_tokens=5000)
    assert full.cache_hit_rate == 1.0


def test_token_usage_to_economic_dict_thresholds() -> None:
    """Test to_economic_dict and the has_effective_cache threshold gate."""
    # Sub-threshold cached tokens (< 1024)
    low_tokens = TokenUsage(prompt_tokens=2000, cached_tokens=500)
    res_low = low_tokens.to_economic_dict(net_savings_usd=0.005)
    assert res_low["cache_hit_rate"] == 0.25
    assert res_low["net_savings_usd"] == 0.005
    assert res_low["has_effective_cache"] is False

    # Sub-threshold net savings (< 0.0001)
    low_savings = TokenUsage(prompt_tokens=5000, cached_tokens=4000)
    res_savings = low_savings.to_economic_dict(net_savings_usd=0.00005)
    assert res_savings["cache_hit_rate"] == 0.8
    assert res_savings["has_effective_cache"] is False

    # Meeting both thresholds (>= 1024 tokens and >= 0.0001 USD)
    qualified = TokenUsage(prompt_tokens=10000, cached_tokens=8000)
    res_qual = qualified.to_economic_dict(net_savings_usd=0.015)
    assert res_qual["cache_hit_rate"] == 0.8
    assert res_qual["net_savings_usd"] == 0.015
    assert res_qual["has_effective_cache"] is True
    # Ensure original fields remain intact
    assert res_qual["prompt_tokens"] == 10000
    assert res_qual["cached_tokens"] == 8000


def test_token_tracker_record_economic_event() -> None:
    """Test that TokenTracker.record populates pending events with economic metrics."""
    tracker = TokenTracker()
    tracker.record(
        usage={
            "prompt_tokens": 12000,
            "completion_tokens": 500,
            "total_tokens": 12500,
            "prompt_tokens_details": {"cached_tokens": 9600},
        },
        model_name="claude-3-5-sonnet",
        duration_ms=1200.0,
        cost_usd=0.012,
        cost_status="actual",
        cache_savings_usd=0.025,
    )

    events = tracker.get_and_clear_pending_events()
    assert len(events) == 1
    event = events[0]
    usage_data = event["usage"]
    assert isinstance(usage_data, dict)
    assert usage_data["cached_tokens"] == 9600
    assert usage_data["cache_hit_rate"] == 0.8
    assert usage_data["net_savings_usd"] == 0.025
    assert usage_data["has_effective_cache"] is True


def test_token_tracker_to_dict_economics() -> None:
    """Test that TokenTracker.to_dict exposes top-level cache economics."""
    tracker = TokenTracker()
    tracker.record(
        usage={
            "prompt_tokens": 8000,
            "completion_tokens": 400,
            "total_tokens": 8400,
            "prompt_tokens_details": {"cached_tokens": 6000},
        },
        cost_usd=0.008,
        cost_status="actual",
        cache_savings_usd=0.018,
    )

    summary = tracker.to_dict()
    assert summary["cache_hit_rate"] == 0.75
    assert summary["has_effective_cache"] is True
    assert summary["total_cache_savings_usd"] == 0.018
