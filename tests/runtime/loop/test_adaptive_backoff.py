"""Unit tests for adaptive exponential backoff pacing."""

from myrm_agent_harness.runtime.loop.backoff import AdaptiveBackoffCalculator


def test_adaptive_backoff_doubling_on_static_response() -> None:
    calc = AdaptiveBackoffCalculator(floor_seconds=60.0, ceiling_seconds=900.0, multiplier=2.0)

    # Round 1: first turn
    d1 = calc.evaluate(
        "Deploy in progress at cluster 1. Checked at 11:58:00.",
        previous_digest="",
        current_delay=60.0,
        consecutive_unchanged=0,
    )
    assert d1.is_changed
    assert d1.next_delay == 60.0
    assert d1.consecutive_unchanged == 0

    # Round 2: same output with clock drift
    d2 = calc.evaluate(
        "Deploy in progress at cluster 1. Checked at 12:00:05.",
        previous_digest=d1.current_digest,
        current_delay=60.0,
        consecutive_unchanged=0,
    )
    assert not d2.is_changed
    assert d2.consecutive_unchanged == 1
    assert d2.next_delay == 120.0

    # Round 3: still unchanged
    d3 = calc.evaluate(
        "Deploy in progress at cluster 1. Checked at 12:02:10.",
        previous_digest=d2.current_digest,
        current_delay=d2.next_delay,
        consecutive_unchanged=d2.consecutive_unchanged,
    )
    assert not d3.is_changed
    assert d3.consecutive_unchanged == 2
    assert d3.next_delay == 240.0


def test_adaptive_backoff_reset_on_change() -> None:
    calc = AdaptiveBackoffCalculator(floor_seconds=60.0, ceiling_seconds=900.0)

    # Initial state backed off to 480s
    decision = calc.evaluate(
        "Deploy completed successfully!",
        previous_digest="previous_fingerprint_hash",
        current_delay=480.0,
        consecutive_unchanged=3,
    )
    assert decision.is_changed
    assert decision.next_delay == 60.0
    assert decision.consecutive_unchanged == 0


def test_adaptive_backoff_alert_bypass() -> None:
    calc = AdaptiveBackoffCalculator(floor_seconds=60.0, ceiling_seconds=900.0)

    # Even if content repeats, a critical alert forces instant snap back to floor
    d1 = calc.evaluate(
        "FATAL: Database connection failed!",
        previous_digest="",
        current_delay=60.0,
        consecutive_unchanged=0,
    )
    assert d1.is_alert
    assert d1.next_delay == 60.0

    d2 = calc.evaluate(
        "FATAL: Database connection failed! 12:01",
        previous_digest=d1.current_digest,
        current_delay=60.0,
        consecutive_unchanged=0,
    )
    # Critical alert bypasses exponential backoff and stays at floor
    assert d2.is_alert
    assert d2.next_delay == 60.0
    assert d2.consecutive_unchanged == 0
