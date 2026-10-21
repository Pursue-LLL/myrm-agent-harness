"""
[INPUT]:
- myrm_agent_harness.observability.token_economics::CacheRoiCalculator
- myrm_agent_harness.observability.token_economics::UnitCostDriftDetector
- myrm_agent_harness.observability.token_economics::RunawayCostGuard
- myrm_agent_harness.observability.token_economics::models

[OUTPUT]:
- Pytest unit tests verifying token economics calculation, cache ROI savings, cost drift detection, and budget runaway circuit breakers.

[POS]:
tests/observability/test_token_economics.py — 长任务 Token 经济学、99% 缓存节流与账单防刺客单元测试。
"""

import pytest

from myrm_agent_harness.observability.token_economics import (
    BudgetGuardPolicy,
    CacheRoiCalculator,
    DriftReasonType,
    GuardStatus,
    RunawayCostGuard,
    TokenUsageSnapshot,
    UnitCostDriftDetector,
)


def test_cache_roi_calculator_ninety_nine_percent_savings() -> None:
    calculator = CacheRoiCalculator()

    # 1. 模拟 DeepSeek-V3 100,000 Prompt Token，其中 99,000 为缓存命中 (99% 命中率)
    snapshot = TokenUsageSnapshot(
        task_id="task-long-01",
        model_name="deepseek-chat",
        task_category="coding_refactor",
        total_prompt_tokens=100_000,
        cached_prompt_tokens=99_000,
        completion_tokens=2_000,
        execution_duration_seconds=120.0,
    )

    metrics = calculator.calculate_savings(snapshot)

    assert metrics.cache_hit_rate_pct == 99.0
    # 无缓存基准：100k * 1.0/1M = 0.1000 + 2k * 2.0/1M = 0.0040 => 0.1040 元
    assert metrics.baseline_cost_rmb == 0.104
    # 实际成本：1k未缓存 * 1.0/1M (0.001) + 99k缓存 * 0.1/1M (0.0099) + 2k输出 (0.004) => 0.0149 元
    assert metrics.actual_cost_rmb == 0.0149
    # 净节省金额：0.104 - 0.0149 = 0.0891 元
    assert metrics.saved_amount_rmb == 0.0891
    # 节省比例约为 85.67%
    assert metrics.saved_percentage > 85.0

    # 2. 边界条件：零 token
    zero_snapshot = TokenUsageSnapshot(
        task_id="task-zero",
        model_name="deepseek-chat",
        task_category="idle",
        total_prompt_tokens=0,
        cached_prompt_tokens=0,
        completion_tokens=0,
        execution_duration_seconds=0.0,
    )
    zero_metrics = calculator.calculate_savings(zero_snapshot)
    assert zero_metrics.cache_hit_rate_pct == 0.0
    assert zero_metrics.saved_amount_rmb == 0.0
    assert zero_metrics.saved_percentage == 0.0


def test_unit_cost_drift_detector_attribution() -> None:
    detector = UnitCostDriftDetector(max_samples=10, drift_threshold_pct=20.0)

    # 1. 注入 3 组历史样本，建立基线 (每 10k tokens 约 0.1 元 => 0.01 元/k)
    for _ in range(3):
        res = detector.record_and_evaluate(
            model_name="deepseek-chat",
            task_category="web_research",
            total_tokens=10_000,
            actual_cost_rmb=0.10,
            cache_hit_rate_pct=95.0,
        )
        assert res.is_significant_drift is False
        assert res.reason == DriftReasonType.NORMAL

    baseline = detector.get_baseline("deepseek-chat", "web_research")
    assert baseline is not None
    assert baseline.sample_count == 3
    assert baseline.average_unit_cost_per_k == 0.01

    # 2. 模拟缓存击穿 (缓存命中率从 95% 跌至 20%)，单位成本涨至 0.025 元/k (+150%)
    bust_alert = detector.record_and_evaluate(
        model_name="deepseek-chat",
        task_category="web_research",
        total_tokens=10_000,
        actual_cost_rmb=0.25,
        cache_hit_rate_pct=20.0,
    )
    assert bust_alert.is_significant_drift is True
    assert bust_alert.reason == DriftReasonType.CACHE_HIT_DEGRADED
    assert "缓存击穿劣化" in bust_alert.explanation

    # 3. 模拟路由降级
    fallback_alert = detector.record_and_evaluate(
        model_name="claude-3-5-sonnet",
        task_category="web_research",
        total_tokens=10_000,
        actual_cost_rmb=0.50,
        cache_hit_rate_pct=90.0,
        is_routed_fallback=True,
    )
    # 没有历史基线时，首批样本不触发显著漂移
    assert fallback_alert.is_significant_drift is False


def test_runaway_cost_guard_circuit_breakers() -> None:
    policy = BudgetGuardPolicy(
        max_allowed_cost_rmb=10.0,
        soft_warning_threshold_rmb=7.0,
        max_allowed_tokens=100_000,
        max_burn_rate_rmb_per_minute=2.0,
    )

    # 1. 正常执行状态
    eval_ok = RunawayCostGuard.evaluate(
        policy=policy,
        current_cost_rmb=2.5,
        current_tokens=20_000,
        duration_seconds=120.0,  # burn_rate = 1.25 元/min
    )
    assert eval_ok.status == GuardStatus.OK
    assert eval_ok.is_paused is False

    # 2. 达到 70% 水位触发软预警
    eval_warn = RunawayCostGuard.evaluate(
        policy=policy,
        current_cost_rmb=7.5,
        current_tokens=50_000,
        duration_seconds=300.0,  # burn_rate = 1.5 元/min
    )
    assert eval_warn.status == GuardStatus.SOFT_WARNING
    assert eval_warn.is_paused is False
    assert "软预警线" in eval_warn.reason

    # 3. 硬预算金额熔断
    eval_cost_trip = RunawayCostGuard.evaluate(
        policy=policy,
        current_cost_rmb=10.5,
        current_tokens=60_000,
        duration_seconds=360.0,
    )
    assert eval_cost_trip.status == GuardStatus.CIRCUIT_BREAKER_TRIPPED
    assert eval_cost_trip.is_paused is True
    assert "硬预算熔断限额" in eval_cost_trip.reason

    # 4. Token 上限熔断
    eval_token_trip = RunawayCostGuard.evaluate(
        policy=policy,
        current_cost_rmb=5.0,
        current_tokens=120_000,
        duration_seconds=360.0,
    )
    assert eval_token_trip.status == GuardStatus.CIRCUIT_BREAKER_TRIPPED
    assert eval_token_trip.is_paused is True
    assert "突破防刺客熔断警戒线" in eval_token_trip.reason

    # 5. 燃烧率骤增熔断 (短时间巨额消耗)
    eval_rate_trip = RunawayCostGuard.evaluate(
        policy=policy,
        current_cost_rmb=2.0,
        current_tokens=10_000,
        duration_seconds=20.0,  # 燃速 = 6.0 元/min > 2.0
    )
    assert eval_rate_trip.status == GuardStatus.CIRCUIT_BREAKER_TRIPPED
    assert eval_rate_trip.is_paused is True
    assert "燃速异常激增" in eval_rate_trip.reason
