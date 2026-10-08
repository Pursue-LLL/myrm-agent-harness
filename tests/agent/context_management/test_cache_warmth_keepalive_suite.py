"""Tests for Context Cache Warmth Gauge and Heartbeat Keep-Alive Suite (Item 328)."""

import threading
from datetime import datetime, timedelta, timezone

import pytest

from myrm_agent_harness.agent.context_management.cache_warmth_keepalive import (
    CacheProviderType,
    CacheWarmthGauge,
    CacheWarmthState,
    ContextCacheWarmthGaugeAndHeartbeatKeepAliveSuite,
    HeartbeatProbeConfig,
    ProviderCacheMatrix,
    calculate_cache_savings,
    calculate_probe_cost,
    format_duration_human,
    get_provider_cache_spec,
)


def test_provider_cache_matrix_and_cost_savings() -> None:
    """Verify matrix resolution and cost savings calculation for different providers."""
    # Anthropic extended (direct endpoint)
    anthropic_spec = get_provider_cache_spec(
        model_name="claude-3-7-sonnet",
        base_url="https://api.anthropic.com/v1",
        is_long_ttl=True,
    )
    assert anthropic_spec.provider_type == CacheProviderType.ANTHROPIC
    assert anthropic_spec.extended_ttl_seconds == 3600
    assert anthropic_spec.supports_explicit_keepalive is True
    assert anthropic_spec.cache_savings_ratio == 0.90

    # Anthropic short TTL
    anthropic_short = get_provider_cache_spec(
        model_name="claude-3-5-haiku",
        base_url="https://some-proxy.com/v1",
        is_long_ttl=False,
    )
    assert anthropic_short.extended_ttl_seconds == 300

    # OpenAI
    openai_spec = get_provider_cache_spec("gpt-4o")
    assert openai_spec.provider_type == CacheProviderType.OPENAI
    assert openai_spec.supports_explicit_keepalive is False

    # DeepSeek
    deepseek_spec = get_provider_cache_spec("deepseek-chat")
    assert deepseek_spec.provider_type == CacheProviderType.DEEPSEEK
    assert deepseek_spec.min_tokens_for_cache == 64
    assert deepseek_spec.supports_explicit_keepalive is True

    # Gemini
    gemini_spec = get_provider_cache_spec("gemini-2.0-flash")
    assert gemini_spec.provider_type == CacheProviderType.GEMINI
    assert gemini_spec.min_tokens_for_cache == 32768

    # Generic
    generic_spec = get_provider_cache_spec("some-local-model")
    assert generic_spec.provider_type == CacheProviderType.GENERIC

    # Cost savings test: 100,000 tokens on Anthropic (3.0 USD standard, 0.3 USD cached)
    tokens_saved, usd_saved = calculate_cache_savings(100_000, anthropic_spec, hit_count=2)
    assert tokens_saved == 200_000
    # 200k * (3.0 - 0.3) / 1M = 0.2 * 2.7 = 0.54 USD
    assert abs(usd_saved - 0.54) < 1e-4

    # Micro probe cost test: 100k cached tokens probe
    probe_cost = calculate_probe_cost(100_000, anthropic_spec, probe_tokens=1)
    # read: 0.1 * 0.3 = 0.03 USD; out: 1/1M * 12 = 0.000012
    assert probe_cost > 0.029 and probe_cost < 0.035


def test_format_duration_human() -> None:
    """Verify human-readable duration formatting."""
    assert format_duration_human(45) == "45 秒"
    assert format_duration_human(120) == "2 分钟"
    assert format_duration_human(125) == "2 分 5 秒"
    assert format_duration_human(3600) == "1 小时"
    assert format_duration_human(3720) == "1 小时 2 分钟"


def test_cache_warmth_gauge_lifecycle() -> None:
    """Verify warmth state machine transitions from warm to critical cooling to cold."""
    gauge = CacheWarmthGauge()
    session_id = "test-session-gauge"
    base_time = datetime(2026, 10, 8, 12, 0, 0, tzinfo=timezone.utc)

    # 1. Below threshold: 500 tokens < 1024
    m_disabled = gauge.record_renewal(
        session_id=session_id,
        cached_tokens=500,
        model_name="claude-3-7-sonnet",
        is_long_ttl=True,
        now=base_time,
    )
    assert m_disabled.state == CacheWarmthState.DISABLED
    assert "未激活" in m_disabled.badge_text
    assert m_disabled.badge_color == "gray"

    # 2. Warm state: 50,000 tokens, 3600s TTL
    m_warm = gauge.record_renewal(
        session_id=session_id,
        cached_tokens=50_000,
        model_name="claude-3-7-sonnet",
        is_long_ttl=True,
        now=base_time,
    )
    assert m_warm.state == CacheWarmthState.WARM
    assert m_warm.remaining_seconds == 3600.0
    assert m_warm.badge_color == "green"
    assert "保温中" in m_warm.badge_text
    assert m_warm.is_keepalive_eligible is False

    # 3. Advance time to 50 minutes later (elapsed 3000s, remaining 600s) -> still warm
    t_50m = base_time + timedelta(minutes=50)
    m_50m = gauge.get_metrics(session_id, now=t_50m)
    assert m_50m.state == CacheWarmthState.WARM
    assert abs(m_50m.remaining_seconds - 600.0) < 1.0

    # 4. Advance time to critical threshold (e.g. 58 minutes 30 seconds later -> remaining 90s <= 120s)
    t_critical = base_time + timedelta(seconds=3510)
    m_crit = gauge.get_metrics(session_id, now=t_critical)
    assert m_crit.state == CacheWarmthState.COOLING_CRITICAL
    assert m_crit.badge_color == "amber"
    assert "即将冷却" in m_crit.badge_text
    assert m_crit.is_keepalive_eligible is True
    assert abs(m_crit.remaining_seconds - 90.0) < 1.0

    # 5. Advance time beyond 3600s -> cold
    t_cold = base_time + timedelta(seconds=3601)
    m_cold = gauge.get_metrics(session_id, now=t_cold)
    assert m_cold.state == CacheWarmthState.COLD
    assert m_cold.badge_color == "gray"
    assert "已冷却" in m_cold.badge_text
    assert m_cold.remaining_seconds == 0.0
    assert m_cold.is_keepalive_eligible is False


def test_keepalive_scheduler_guardrails() -> None:
    """Verify keepalive scheduler checks thresholds, caps, and idle timeout."""
    suite = ContextCacheWarmthGaugeAndHeartbeatKeepAliveSuite(
        probe_config=HeartbeatProbeConfig(
            enabled=True,
            min_tokens_threshold=1000,
            critical_window_seconds=120,
            max_consecutive_heartbeats=2,
            max_idle_seconds=7200,  # 2 hours
        )
    )
    session_id = "test-session-guardrails"
    t0 = datetime(2026, 10, 8, 10, 0, 0, tzinfo=timezone.utc)

    # User interacts and warms cache
    suite.record_session_interaction(
        session_id=session_id,
        cached_tokens=20_000,
        model_name="claude-3-7-sonnet",
        is_long_ttl=True,
        now=t0,
    )

    # 1. Warm phase: should NOT probe
    d1 = suite.evaluate_keepalive_probe(session_id, now=t0 + timedelta(minutes=10))
    assert d1.should_probe is False
    assert "warm" in d1.reason.lower()

    # 2. Critical phase (at 58m30s, remaining 90s <= 120s): should probe!
    t_crit = t0 + timedelta(seconds=3510)
    d2 = suite.evaluate_keepalive_probe(session_id, now=t_crit)
    assert d2.should_probe is True
    assert d2.probe_token_budget == 1

    # Execute 1st keepalive probe
    rec1 = suite.record_probe_executed(session_id, probe_tokens=1, now=t_crit)
    assert rec1.consecutive_heartbeat_index == 1
    assert rec1.renewed_ttl_seconds == 3600

    # After probe execution, gauge is re-warmed
    m_after_p1 = suite.get_warmth_metrics(session_id, now=t_crit)
    assert m_after_p1.state == CacheWarmthState.WARM
    assert abs(m_after_p1.remaining_seconds - 3600.0) < 1.0

    # 3. Fast-forward to 2nd critical window (3510s after 1st probe)
    t_crit2 = t_crit + timedelta(seconds=3510)
    d3 = suite.evaluate_keepalive_probe(session_id, now=t_crit2)
    assert d3.should_probe is True

    # Execute 2nd keepalive probe
    rec2 = suite.record_probe_executed(session_id, probe_tokens=1, now=t_crit2)
    assert rec2.consecutive_heartbeat_index == 2

    # 4. Fast-forward to 3rd critical window: max consecutive heartbeats (2) reached!
    t_crit3 = t_crit2 + timedelta(seconds=3510)
    d4 = suite.evaluate_keepalive_probe(session_id, now=t_crit3)
    assert d4.should_probe is False
    assert "max consecutive" in d4.reason.lower()

    # 5. User types a new message -> resets consecutive heartbeat counter
    t_user = t_crit3 + timedelta(seconds=10)
    suite.record_session_interaction(
        session_id=session_id,
        cached_tokens=22_000,
        model_name="claude-3-7-sonnet",
        is_user_interaction=True,
        now=t_user,
    )
    assert suite.scheduler.get_consecutive_count(session_id) == 0


def test_ui_capsule_and_savings_tracking() -> None:
    """Verify UI capsule payload and cumulative savings accumulation."""
    suite = ContextCacheWarmthGaugeAndHeartbeatKeepAliveSuite()
    session_id = "test-session-ui"
    t0 = datetime(2026, 10, 8, 14, 0, 0, tzinfo=timezone.utc)

    # Initial turn (write cache)
    suite.record_session_interaction(
        session_id=session_id,
        cached_tokens=80_000,
        model_name="claude-3-7-sonnet",
        is_hit=False,
        now=t0,
    )

    capsule1 = suite.get_ui_capsule(session_id, now=t0)
    assert capsule1["state"] == "warm"
    assert capsule1["badge_color"] == "green"
    assert "80,000" not in str(capsule1["badge_text"])  # badge text focuses on time
    assert capsule1["cached_tokens"] == 80_000
    assert capsule1["cumulative_cost_saved_usd"] == 0.0

    # Second turn 5 minutes later (cache hit!)
    t1 = t0 + timedelta(minutes=5)
    suite.record_session_interaction(
        session_id=session_id,
        cached_tokens=80_000,
        model_name="claude-3-7-sonnet",
        is_hit=True,
        now=t1,
    )

    capsule2 = suite.get_ui_capsule(session_id, now=t1)
    assert capsule2["cumulative_tokens_saved"] == 80_000
    assert float(capsule2["cumulative_cost_saved_usd"]) > 0.20  # ~0.216 USD saved


def test_concurrency_and_cleanup() -> None:
    """Verify thread safety during concurrent renewals and queries."""
    suite = ContextCacheWarmthGaugeAndHeartbeatKeepAliveSuite()
    num_threads = 8
    iterations = 25
    session_prefix = "concurrent-session-"

    def worker(worker_id: int) -> None:
        sid = f"{session_prefix}{worker_id % 3}"
        for i in range(iterations):
            suite.record_session_interaction(
                session_id=sid,
                cached_tokens=5000 + i * 100,
                model_name="claude-3-7-sonnet",
                is_hit=(i % 2 == 0),
            )
            suite.get_warmth_metrics(sid)
            suite.get_ui_capsule(sid)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Check metrics existence
    for s_idx in range(3):
        sid = f"{session_prefix}{s_idx}"
        m = suite.get_warmth_metrics(sid)
        assert m.cached_tokens > 0

    # Reset
    suite.reset_session(f"{session_prefix}0")
    m_reset = suite.get_warmth_metrics(f"{session_prefix}0")
    assert m_reset.state == CacheWarmthState.COLD
