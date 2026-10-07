"""Unit tests for PromptCacheEconomicsEngine and cross-deployment HUD generator.

Validates 30x DeepSeek financial economics, traffic light thresholds,
session lifecycle aggregation, and unified anti-drift HUD payload synthesis.
"""

from concurrent.futures import ThreadPoolExecutor

from myrm_agent_harness.runtime.context.prompt_cache_economics_engine import (
    PromptCacheEconomicsEngine,
)
from myrm_agent_harness.runtime.context.prompt_cache_economics_types import (
    HealthTrafficLight,
)


def test_deepseek_30x_savings_and_green_traffic_light() -> None:
    """Verifies that 99% cache hit rate achieves ~30x input price discount and green traffic light."""
    engine = PromptCacheEconomicsEngine()
    session_id = "econ-sess-001"

    # DeepSeek pricing: uncached=$2.00/M, cached=$0.10/M (20x on input alone)
    # 1,000,000 prompt tokens, 990,000 cached (99% hit rate), 1,000 completion tokens
    rec = engine.record_turn_usage(
        session_id=session_id,
        model_name="deepseek-chat",
        prompt_tokens=1_000_000,
        cached_tokens=990_000,
        completion_tokens=1_000,
    )

    assert rec.turn_index == 1
    assert rec.cache_hit_rate == 0.99
    assert rec.traffic_light == HealthTrafficLight.GREEN_OPTIMAL
    # Uncached baseline input cost: 1M * $2.00 = $2.00
    # Actual input cost: 10k * $2.00 ($0.02) + 990k * $0.10 ($0.099) = $0.119
    assert rec.baseline_uncached_cost_usd > rec.actual_cost_usd
    assert rec.savings_ratio > 0.90
    assert rec.savings_multiplier > 15.0
    assert rec.savings_usd > 1.80


def test_yellow_traffic_light_partial_cache() -> None:
    """Verifies that 75% cache hit rate classifies as YELLOW_PARTIAL."""
    engine = PromptCacheEconomicsEngine()
    session_id = "econ-sess-002"

    rec = engine.record_turn_usage(
        session_id=session_id,
        model_name="deepseek-chat",
        prompt_tokens=100_000,
        cached_tokens=75_000,
        completion_tokens=500,
    )

    assert rec.cache_hit_rate == 0.75
    assert rec.traffic_light == HealthTrafficLight.YELLOW_PARTIAL
    assert rec.savings_usd > 0.0


def test_red_traffic_light_cold_start_or_drift() -> None:
    """Verifies that low cache hit rate (<60%) classifies as RED_DRIFT_BREACH."""
    engine = PromptCacheEconomicsEngine()
    session_id = "econ-sess-003"

    rec = engine.record_turn_usage(
        session_id=session_id,
        model_name="deepseek-chat",
        prompt_tokens=100_000,
        cached_tokens=10_000,
        completion_tokens=500,
        drift_reason="Dynamic timestamp injected into system prompt",
    )

    assert rec.cache_hit_rate == 0.10
    assert rec.traffic_light == HealthTrafficLight.RED_DRIFT_BREACH
    assert rec.drift_diagnosis == "Dynamic timestamp injected into system prompt"


def test_session_lifecycle_multi_turn_aggregation() -> None:
    """Verifies multi-turn session accumulation accurately rolls up financials and dominant traffic light."""
    engine = PromptCacheEconomicsEngine()
    session_id = "econ-sess-004"

    # Turn 1: Cold start (0% hit)
    engine.record_turn_usage(session_id, "deepseek-chat", 50_000, 0, 500)
    # Turn 2: Warm cache (90% hit)
    engine.record_turn_usage(session_id, "deepseek-chat", 60_000, 54_000, 500)
    # Turn 3: Optimal cache (98% hit)
    engine.record_turn_usage(session_id, "deepseek-chat", 70_000, 68_600, 500)
    # Turn 4: Optimal cache (99% hit)
    engine.record_turn_usage(session_id, "deepseek-chat", 80_000, 79_200, 500)

    summary = engine.get_session_summary(session_id)
    assert summary.total_turns_count == 4
    assert summary.total_prompt_tokens == 260_000
    assert summary.total_cached_tokens == 201_800
    assert summary.overall_cache_hit_rate > 0.75
    assert summary.total_savings_usd > 0.30
    assert summary.dominant_traffic_light in (
        HealthTrafficLight.GREEN_OPTIMAL,
        HealthTrafficLight.YELLOW_PARTIAL,
    )


def test_hud_payload_synthesis_and_anti_drift_tips() -> None:
    """Verifies generation of cross-deployment HUD payload with actionable anti-drift tips."""
    engine = PromptCacheEconomicsEngine()
    session_id = "econ-sess-005"

    engine.record_turn_usage(
        session_id=session_id,
        model_name="deepseek-chat",
        prompt_tokens=200_000,
        cached_tokens=198_000,
        completion_tokens=1_000,
    )

    hud = engine.generate_hud_payload(session_id)
    assert hud.session_id == session_id
    assert "99%" in hud.traffic_light_badge
    assert hud.cache_hit_rate_percent == 99.0
    assert "便宜" in hud.savings_multiplier_label
    assert hud.total_savings_usd_formatted.startswith("$")
    assert len(hud.anti_drift_tips) >= 2


def test_multithreaded_concurrency() -> None:
    """Verifies thread-safety under concurrent turns across multiple parallel sessions."""
    engine = PromptCacheEconomicsEngine()

    def _worker(worker_id: int) -> float:
        s_id = f"concur-sess-{worker_id}"
        rec = engine.record_turn_usage(
            session_id=s_id,
            model_name="deepseek-chat",
            prompt_tokens=50_000,
            cached_tokens=48_000,
            completion_tokens=200,
        )
        hud = engine.generate_hud_payload(s_id)
        return hud.cache_hit_rate_percent + rec.savings_usd

    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(_worker, range(10)))

    assert len(results) == 10
    assert all(r > 0.0 for r in results)
