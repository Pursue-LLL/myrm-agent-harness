"""Unit tests for Resumed Session History Token Exclusion and Net Run Usage Meter Suite.

Verifies pre-existing history exclusion upon session resumption, net incremental task billing,
prompt cache discount accounting, first-turn latching, and auditable ledger telemetry.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management import (
    NetRunUsage,
    NetRunUsageMeter,
    RawTurnUsage,
    ResumedSessionHistoryTokenExclusionAndNetRunUsageMeterSuite,
    ResumptionBaseline,
    SessionUsageSummary,
    UsageBillingLedgerRecord,
)


def test_net_run_usage_meter_isolation_and_cost() -> None:
    """Verify isolation of incremental tokens from legacy baseline and cost estimation."""
    meter = NetRunUsageMeter(
        input_rate_per_m=3.00,
        output_rate_per_m=15.00,
        cache_discount_ratio=0.10,
    )

    baseline = ResumptionBaseline(
        session_id="sess-resumed-01",
        resumed_history_tokens=32000,
        resumed_turn_count=20,
        resumed_at_iso="2026-10-08T00:00:00Z",
    )

    # 1. First turn after resumption: gross prompt contains 35,000 tokens (32k history + 3k new)
    raw_first_turn = RawTurnUsage(
        gross_prompt_tokens=35000,
        completion_tokens=500,
        cached_prompt_tokens=30000,
    )
    net_first = meter.calculate_net_run_usage(
        raw_usage=raw_first_turn,
        baseline=baseline,
        is_first_resumed_turn=True,
    )

    assert net_first.excluded_history_tokens == 32000
    assert net_first.net_prompt_tokens == 3000
    assert net_first.completion_tokens == 500
    assert net_first.net_billable_tokens == 3500
    assert net_first.gross_physical_tokens == 35500
    assert net_first.cache_hit_ratio > 0.85

    # Cost calculated strictly on net incremental tokens, not the 35,500 gross tokens
    cost = meter.estimate_cost(net_first, raw_first_turn)
    assert cost < 0.02  # Less than 2 cents, instead of > 10 cents for 35k gross

    # 2. Subsequent normal turn: no history exclusion
    raw_next_turn = RawTurnUsage(
        gross_prompt_tokens=36000,
        completion_tokens=600,
        cached_prompt_tokens=35000,
    )
    net_next = meter.calculate_net_run_usage(
        raw_usage=raw_next_turn,
        baseline=baseline,
        is_first_resumed_turn=False,
    )
    assert net_next.excluded_history_tokens == 0
    assert net_next.net_prompt_tokens == 36000
    assert net_next.net_billable_tokens == 36600


def test_resumed_usage_suite_first_turn_latch_and_ledger() -> None:
    """Verify suite resumption baseline latching across consecutive dialogue turns."""
    suite = ResumedSessionHistoryTokenExclusionAndNetRunUsageMeterSuite()

    # Register baseline: 40,000 tokens inherited from prior workstream
    baseline = suite.register_resumption_baseline(
        session_id="sess-audit-100",
        historical_tokens=40000,
        turn_count=25,
        prior_cost=0.50,
    )
    assert baseline.resumed_history_tokens == 40000

    # Turn 1: Should exclude the 40,000 tokens
    raw_t1 = RawTurnUsage(gross_prompt_tokens=42000, completion_tokens=300)
    rec1 = suite.meter_turn_usage(session_id="sess-audit-100", raw_usage=raw_t1, turn_index=26)
    assert rec1.is_resumed_turn is True
    assert rec1.net_usage.excluded_history_tokens == 40000
    assert rec1.net_usage.net_prompt_tokens == 2000
    assert rec1.net_usage.net_billable_tokens == 2300

    # Turn 2: Should NOT exclude history again (latch triggered)
    raw_t2 = RawTurnUsage(gross_prompt_tokens=43000, completion_tokens=400)
    rec2 = suite.meter_turn_usage(session_id="sess-audit-100", raw_usage=raw_t2, turn_index=27)
    assert rec2.is_resumed_turn is False
    assert rec2.net_usage.excluded_history_tokens == 0
    assert rec2.net_usage.net_prompt_tokens == 43000


def test_session_summary_and_global_telemetry() -> None:
    """Verify session cumulative summary and cross-session global telemetry."""
    suite = ResumedSessionHistoryTokenExclusionAndNetRunUsageMeterSuite()

    suite.register_resumption_baseline(
        session_id="sess-stats-1",
        historical_tokens=20000,
        turn_count=10,
        prior_cost=0.15,
    )

    raw_turn = RawTurnUsage(gross_prompt_tokens=22000, completion_tokens=500)
    suite.meter_turn_usage(session_id="sess-stats-1", raw_usage=raw_turn, turn_index=11)

    summary = suite.get_session_summary("sess-stats-1")
    assert summary.session_id == "sess-stats-1"
    assert summary.total_turns == 1
    assert summary.total_excluded_history_tokens == 20000
    assert summary.lifetime_gross_tokens == 22500
    assert summary.lifetime_net_run_tokens == 2500
    assert summary.total_cost >= 0.15  # Includes prior cost

    # Global telemetry
    telemetry = suite.get_global_telemetry()
    assert telemetry["total_turns_metered"] == 1
    assert telemetry["total_sessions_resumed"] == 1
    assert telemetry["total_excluded_history_tokens"] == 20000
    assert telemetry["total_net_billable_tokens"] == 2500
