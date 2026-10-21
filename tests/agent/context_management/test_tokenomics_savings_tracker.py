"""Unit tests for Tokenomics Savings Tracker and Live Cost HUD."""

from __future__ import annotations

import concurrent.futures

from myrm_agent_harness.agent.context_management.tracking import (
    TokenomicsSavingsTracker,
    get_global_tokenomics_tracker,
)


def test_pricing_resolution() -> None:
    tracker = TokenomicsSavingsTracker()

    tier_ds = tracker.resolve_pricing("deepseek-v3-0324")
    assert tier_ds.model_pattern == "deepseek-v3"
    assert tier_ds.input_cost_per_million == 0.27

    tier_sonnet = tracker.resolve_pricing("anthropic/claude-3-5-sonnet-20241022")
    assert tier_sonnet.model_pattern == "claude-3-5-sonnet"
    assert tier_sonnet.input_cost_per_million == 3.00

    tier_gpt = tracker.resolve_pricing("openai/gpt-4o-mini-2024-07-18")
    assert tier_gpt.model_pattern == "gpt-4o-mini"
    assert tier_gpt.input_cost_per_million == 0.15

    tier_fallback = tracker.resolve_pricing("unknown-custom-model-v1")
    assert tier_fallback.model_pattern == "default"
    assert tier_fallback.input_cost_per_million == 1.00


def test_single_compaction_recording_and_cost() -> None:
    tracker = TokenomicsSavingsTracker()

    # Raw 10,000 tokens, compacted to 6,000 tokens (saved 4,000 tokens, 40%)
    # Model: deepseek-v3 (input: $0.27 / 1M) -> 4,000 / 1,000,000 * 0.27 = $0.00108
    event = tracker.record_compaction(
        operator_name="gcf_tabular",
        raw_tokens=10_000,
        compacted_tokens=6_000,
        model_name="deepseek-v3",
    )

    assert event.saved_tokens == 4_000
    assert event.saved_ratio == 0.40
    assert event.operator_name == "gcf_tabular"
    assert event.estimated_cost_saved_usd == 0.00108

    summary = tracker.get_hud_summary(session_id="session-101")
    assert summary.session_id == "session-101"
    assert summary.total_raw_tokens == 10_000
    assert summary.total_compacted_tokens == 6_000
    assert summary.total_saved_tokens == 4_000
    assert summary.overall_savings_percentage == 40.0
    assert summary.total_cost_saved_usd == 0.0011
    assert "4,000" in summary.formatted_hud_badge


def test_prompt_cache_hits_cost_delta() -> None:
    tracker = TokenomicsSavingsTracker()

    # Model: claude-3-5-sonnet (input: $3.00, cache_read: $0.30 -> delta $2.70 / 1M)
    # 1,000,000 cached tokens saved $2.70
    event = tracker.record_compaction(
        operator_name="explicit_cache",
        raw_tokens=5_000,
        compacted_tokens=5_000,
        model_name="claude-3-5-sonnet",
        cached_tokens=100_000,  # 0.1M * $2.70 = $0.27
    )

    assert event.cached_tokens == 100_000
    assert event.saved_tokens == 0
    assert event.estimated_cost_saved_usd == 0.27

    summary = tracker.get_hud_summary()
    assert summary.total_prompt_cache_hits_tokens == 100_000
    assert summary.total_cost_saved_usd == 0.27


def test_operator_breakdown_and_hud_summary() -> None:
    tracker = TokenomicsSavingsTracker()

    tracker.record_compaction("gcf_tabular", 10_000, 6_000, model_name="gpt-4o")
    tracker.record_compaction("unified_diff", 5_000, 3_000, model_name="gpt-4o")
    tracker.record_compaction("repeated_logs", 8_000, 2_000, model_name="gpt-4o")

    summary = tracker.get_hud_summary(session_id="chat-999")
    assert summary.total_saved_tokens == (4_000 + 2_000 + 6_000)
    assert summary.operator_breakdown["gcf_tabular"] == 4_000
    assert summary.operator_breakdown["unified_diff"] == 2_000
    assert summary.operator_breakdown["repeated_logs"] == 6_000
    assert summary.recent_events_count == 3
    assert "🎉 累计节省 12,000 Tokens" in summary.formatted_hud_badge


def test_sliding_window_history_limit() -> None:
    tracker = TokenomicsSavingsTracker(max_history_events=5)

    for i in range(10):
        tracker.record_compaction(f"op_{i}", 100, 50)

    summary = tracker.get_hud_summary()
    assert summary.recent_events_count == 5
    assert summary.total_saved_tokens == 500


def test_reset_functionality() -> None:
    tracker = TokenomicsSavingsTracker()
    tracker.record_compaction("op", 1_000, 200)

    summary_before = tracker.get_hud_summary()
    assert summary_before.total_saved_tokens == 800

    tracker.reset()
    summary_after = tracker.get_hud_summary()
    assert summary_after.total_saved_tokens == 0
    assert summary_after.total_cost_saved_usd == 0.0
    assert summary_after.recent_events_count == 0


def test_global_tracker_singleton() -> None:
    g1 = get_global_tokenomics_tracker()
    g2 = get_global_tokenomics_tracker()
    assert g1 is g2


def test_concurrent_multithreaded_recording() -> None:
    tracker = TokenomicsSavingsTracker(max_history_events=500)

    def worker(i: int) -> None:
        tracker.record_compaction(f"worker_{i % 5}", 1_000, 600, model_name="deepseek-v3")

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(worker, i) for i in range(50)]
        concurrent.futures.wait(futures)

    summary = tracker.get_hud_summary()
    assert summary.total_raw_tokens == 50 * 1_000
    assert summary.total_compacted_tokens == 50 * 600
    assert summary.total_saved_tokens == 50 * 400
    assert summary.recent_events_count == 50
