"""
[INPUT]: KnowledgeCompoundingAggregator and mock metric signals.
[OUTPUT]: Pytest test cases verifying five-metric aggregation, compounding tiers, and regression alerts.
[POS]: myrm-agent-harness/tests/observability/test_knowledge_compounding.py
"""

import pytest

from myrm_agent_harness.observability.knowledge_compounding import (
    CompoundingMetricName,
    CompoundingMetricPoint,
    KnowledgeCompoundingAggregator,
    KnowledgeCompoundingHealthSnapshot,
    MetricHealthStatus,
)


def test_knowledge_compounding_aggregator_healthy_growth() -> None:
    aggregator = KnowledgeCompoundingAggregator()

    snapshot = aggregator.evaluate(
        repeated_error_rate_pct=2.0,
        knowledge_hit_rate_pct=75.0,
        human_corrections_count=3,
        first_pass_success_rate_pct=92.0,
        stale_knowledge_ratio_pct=5.0,
        window_days=30,
    )

    assert isinstance(snapshot, KnowledgeCompoundingHealthSnapshot)
    assert snapshot.overall_score >= 85.0
    assert snapshot.compounding_tier == "HIGHLY_COMPOUNDING"
    assert len(snapshot.regression_alerts) == 0
    assert snapshot.window_days == 30

    metrics = snapshot.metrics
    assert len(metrics) == 5

    # 验证五大指标都在且健康
    for key in [
        CompoundingMetricName.REPEATED_ERROR_RATE.value,
        CompoundingMetricName.KNOWLEDGE_HIT_RATE.value,
        CompoundingMetricName.HUMAN_CORRECTIONS_COUNT.value,
        CompoundingMetricName.FIRST_PASS_SUCCESS_RATE.value,
        CompoundingMetricName.STALE_KNOWLEDGE_RATIO.value,
    ]:
        assert key in metrics
        assert metrics[key].status == MetricHealthStatus.HEALTHY

    # 验证序列化结构
    raw_dict = snapshot.to_dict()
    assert "overall_score" in raw_dict
    assert raw_dict["compounding_tier"] == "HIGHLY_COMPOUNDING"
    assert isinstance(raw_dict["metrics"], dict)


def test_knowledge_compounding_aggregator_regression_and_alerts() -> None:
    aggregator = KnowledgeCompoundingAggregator()

    snapshot = aggregator.evaluate(
        repeated_error_rate_pct=18.5,  # 严重重复错误
        knowledge_hit_rate_pct=22.0,   # 命中率极低
        human_corrections_count=22,    # 频繁人工纠正
        first_pass_success_rate_pct=52.0,  # 一次通过率低下
        stale_knowledge_ratio_pct=38.0,    # 知识库严重腐化
        window_days=14,
    )

    assert snapshot.overall_score < 50.0
    assert snapshot.compounding_tier == "REGRESSING"
    assert snapshot.window_days == 14

    # 验证五大指标均触发 CRITICAL 状态
    for metric_point in snapshot.metrics.values():
        assert metric_point.status == MetricHealthStatus.CRITICAL

    # 验证报警列表触发了 5 条警告
    assert len(snapshot.regression_alerts) == 5
    alert_text = " ".join(snapshot.regression_alerts)
    assert "重复错误率偏高" in alert_text
    assert "跨会话知识命中率偏低" in alert_text
    assert "人工纠正与打回重做频次过高" in alert_text
    assert "任务一次通过率低于基线" in alert_text
    assert "过期与被忽视知识占比达到" in alert_text
