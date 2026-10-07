"""Unit tests for Smart Idle Cache-Preserving Auto-Compactor Suite.

Verifies idle eligibility evaluation across cache TTL windows, opportunistic pre-compaction
at 0.1x discount rates, cold storage checkpoint archival, and zero-wait user wakeup.
"""

from __future__ import annotations

import time
import pytest

from myrm_agent_harness.agent.context_management import (
    CacheWindowStatus,
    IdleCompactionAction,
    IdleCompactorConfig,
    IdleEligibilityEvaluator,
    OpportunisticCompactorEngine,
    SmartIdleCachePreservingAutoCompactorSuite,
)


def test_idle_eligibility_evaluator_lifecycle() -> None:
    """Verify idle eligibility transitions across token thresholds and cache TTL windows."""
    config = IdleCompactorConfig(
        min_token_threshold=12000,
        cache_ttl_seconds=3600,
        idle_trigger_min_seconds=1800,
        idle_trigger_max_seconds=3000,
        cache_hit_rate_multiplier=0.1,
        full_prefill_multiplier=1.0,
    )
    evaluator = IdleEligibilityEvaluator(config)
    now = 10000.0

    # 1. Below token threshold (<12k tokens)
    ev_low = evaluator.evaluate(
        session_id="sess-001",
        current_tokens=5000,
        last_turn_timestamp_epoch=now - 2000.0,
        current_timestamp_epoch=now,
    )
    assert ev_low.action == IdleCompactionAction.SKIP_BELOW_TOKEN_BUDGET
    assert ev_low.should_compact is False

    # 2. Too early (only 10 mins idle, user likely still active)
    ev_early = evaluator.evaluate(
        session_id="sess-002",
        current_tokens=16000,
        last_turn_timestamp_epoch=now - 600.0,  # 10 mins
        current_timestamp_epoch=now,
    )
    assert ev_early.action == IdleCompactionAction.SKIP_TOO_EARLY
    assert ev_early.cache_status == CacheWindowStatus.HOT_FRESH
    assert ev_early.should_compact is False

    # 3. Cache already expired (>60 mins idle, 3800s)
    ev_expired = evaluator.evaluate(
        session_id="sess-003",
        current_tokens=16000,
        last_turn_timestamp_epoch=now - 3800.0,
        current_timestamp_epoch=now,
    )
    assert ev_expired.action == IdleCompactionAction.SKIP_CACHE_ALREADY_EXPIRED
    assert ev_expired.cache_status == CacheWindowStatus.EXPIRED_COLD
    assert ev_expired.should_compact is False

    # 4. Golden opportunistic window (35 mins idle, 2100s)
    ev_golden = evaluator.evaluate(
        session_id="sess-004",
        current_tokens=20000,
        last_turn_timestamp_epoch=now - 2100.0,
        current_timestamp_epoch=now,
    )
    assert ev_golden.action == IdleCompactionAction.TRIGGER_OPPORTUNISTIC
    assert ev_golden.cache_status == CacheWindowStatus.OPPORTUNISTIC_EXPIRING_SOON
    assert ev_golden.should_compact is True
    # 0.1x vs 1.0x -> 90% savings ratio
    assert abs(ev_golden.potential_savings_ratio - 0.90) < 1e-4
    assert ev_golden.estimated_hot_compaction_cost_units == 2000.0
    assert ev_golden.estimated_cold_compaction_cost_units == 20000.0


def test_opportunistic_compactor_engine_execution_and_wakeup() -> None:
    """Verify background pre-compaction execution, durable archive, and zero-wait wakeup."""
    config = IdleCompactorConfig()
    evaluator = IdleEligibilityEvaluator(config)
    engine = OpportunisticCompactorEngine(config)

    now = 20000.0
    eval_res = evaluator.evaluate(
        session_id="sess-prod-77",
        current_tokens=18000,
        last_turn_timestamp_epoch=now - 2400.0,  # 40 mins idle
        current_timestamp_epoch=now,
    )
    assert eval_res.should_compact is True

    messages = [
        {"role": "user", "content": "Analyze PostgreSQL schema and optimize query performance."},
        {"role": "assistant", "content": "Indexing strategy proposed."},
        {"role": "user", "content": "Execute migration on table user_sessions."},
    ]

    result = engine.execute_opportunistic_compaction(
        evaluation=eval_res,
        messages_repr=messages,
    )

    assert result.success is True
    assert result.was_cache_hot_utilized is True
    assert result.saved_tokens > 17000
    assert result.tokens_compressed_ratio > 0.95
    assert result.cost_units_incurred == 1800.0  # 18000 * 0.1
    assert result.cost_units_avoided == 16200.0  # 18000 * 0.9

    # Verify archive preservation
    archive = engine.get_archive("sess-prod-77")
    assert archive is not None
    assert archive.original_tokens == 18000
    assert "user_sessions" in archive.checkpoint_summary

    # Simulate user resuming 1.5 hours later
    wakeup = engine.record_wakeup("sess-prod-77", idle_total_seconds=5400.0)
    assert wakeup.cold_prefill_prevented is True
    assert wakeup.tokens_served_immediately == archive.compacted_tokens
    assert wakeup.estimated_time_to_first_token_reduction_ms > 200.0


def test_smart_idle_compactor_suite_facade() -> None:
    """Verify master suite orchestration and cumulative financial savings metrics."""
    suite = SmartIdleCachePreservingAutoCompactorSuite()
    now = time.time()

    # 1. Run opportunistic compaction via facade
    res = suite.compact_if_eligible(
        session_id="sess-vip-101",
        current_tokens=25000,
        last_turn_timestamp_epoch=now - 2200.0,
        current_timestamp_epoch=now,
    )
    assert res.success is True
    assert res.saved_tokens > 24000

    # 2. Check archive retrieval
    arch = suite.get_archived_checkpoint("sess-vip-101")
    assert arch is not None
    assert arch.original_tokens == 25000

    # 3. Simulate user wakeup
    wakeup = suite.notify_user_wakeup("sess-vip-101", idle_total_seconds=4000.0)
    assert wakeup.cold_prefill_prevented is True

    # 4. Check cumulative telemetry metrics
    metrics = suite.get_aggregate_metrics()
    assert metrics["opportunistic_compactions_executed"] == 1
    assert int(metrics["total_tokens_compressed"]) > 24000
    assert float(metrics["total_cold_cost_units_avoided"]) == 22500.0
    assert float(metrics["net_financial_savings_ratio"]) == 0.90
