"""AdaptiveRouter V2 成本学习功能测试"""

import tempfile
from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.web_fetch.fetchers.protocols import FetcherType
from myrm_agent_harness.toolkits.web_fetch.router.adaptive_router import AdaptiveRouter


@pytest.fixture
def router():
    with tempfile.TemporaryDirectory() as tmpdir:
        rules_file = Path(tmpdir) / "test_rules.pkl"
        yield AdaptiveRouter(rules_file=rules_file)


def test_seed_costs(router):
    """测试种子成本（多维度：延迟 + CPU + 内存）"""
    for fetcher_type in FetcherType:
        cost = router._estimate_cost(fetcher_type)
        assert cost.latency_ms > 0
        assert cost.cpu_percent > 0
        assert cost.memory_mb > 0
        assert cost.latency_ms == router.SEED_COSTS[fetcher_type].latency_ms
        assert cost.cpu_percent == router.SEED_COSTS[fetcher_type].cpu_percent
        assert cost.memory_mb == router.SEED_COSTS[fetcher_type].memory_mb


def test_progressive_learning(router):
    """测试渐进式学习（权重混合种子成本和实测成本）"""
    for _i in range(20):
        router.report_result("https://test.com", FetcherType.HTTP, success=True, latency_ms=80.0)

    cost = router._estimate_cost(FetcherType.HTTP)
    assert 80 < cost.latency_ms < 100


def test_cost_optimized_selection(router):
    """测试成本优化决策"""
    domain = "github.com"

    for _ in range(30):
        router.report_result(f"https://{domain}/test", FetcherType.HTTP, success=True, latency_ms=100.0)

    for _ in range(30):
        router.report_result(f"https://{domain}/test", FetcherType.BROWSER, success=True, latency_ms=1500.0)

    decision = router.select(f"https://{domain}/new")

    assert decision.reason in ["learning_cache", "cost_optimized", "persistent_rule"]


def test_expected_cost_calculation(router):
    """测试期望成本计算（期望成本 = 归一化加权成本 / 成功率）"""
    domain = "test.com"

    for i in range(50):
        router.report_result(f"https://{domain}/{i}", FetcherType.HTTP, success=True, latency_ms=100.0)

    expected_cost = router._calculate_expected_cost(domain, FetcherType.HTTP)
    # 归一化后：0.1s * 1.0 + 0.02 * 0.3 + 0.01 * 0.2 = 0.108
    assert 0.10 <= expected_cost <= 0.12


def test_stats_include_cost_learning(router):
    """测试统计信息包含成本学习数据"""
    router.report_result("https://test.com", FetcherType.HTTP, success=True, latency_ms=120.0)

    stats = router.get_stats()
    assert "cost_learning" in stats
    assert "HTTP" in stats["cost_learning"]
    assert stats["cost_learning"]["HTTP"]["samples"] == 1
    assert stats["cost_learning"]["HTTP"]["avg_latency_ms"] == 120.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
