"""AdaptiveRouter 边界条件和异常处理测试

专门覆盖未测试的边界条件：
- URL 解析异常
- 堆空时的 fallback 逻辑
- 异步保存的异常处理
- 定期清理触发
"""

import tempfile
import time
from pathlib import Path

from myrm_agent_harness.toolkits.web_fetch.fetchers.protocols import FetcherType
from myrm_agent_harness.toolkits.web_fetch.router import AdaptiveRouter


def test_url_parsing_exception():
    """测试 URL 解析异常处理（覆盖 adaptive_router.py:148-149）"""
    with tempfile.TemporaryDirectory() as tmpdir:
        router = AdaptiveRouter(rules_file=Path(tmpdir) / "test.pkl")

        invalid_urls = [
            "not-a-url",
            "://invalid",
            "",
            "http://",
            "https://",
        ]

        for url in invalid_urls:
            decision = router.select(url)
            assert decision.fetcher_type == FetcherType.HTTP
            router.report_result(url, decision.fetcher_type, success=True, latency_ms=50.0)

        print(" URL 解析异常处理正确")


def test_heap_empty_fallback():
    """测试堆空时的 O(n) fallback 逻辑（覆盖 maintenance.py:73-77, 100-103）"""
    with tempfile.TemporaryDirectory() as tmpdir:
        router = AdaptiveRouter(
            rules_file=Path(tmpdir) / "test.pkl",
            max_cache_size=5,
            max_persistent_rules=3,
        )

        for i in range(6):
            url = f"https://domain{i}.com/page"
            router.select(url)
            router.report_result(url, FetcherType.HTTP, True, latency_ms=50.0)

        router._learning_heap.clear()

        router.select("https://new-domain.com/page")
        router.report_result("https://new-domain.com/page", FetcherType.HTTP, True, latency_ms=50.0)

        assert len(router._learning_cache) <= 5

        for i in range(10, 15):
            url = f"https://perm{i}.com/page"
            for _ in range(100):
                router.select(url)
                router.report_result(url, FetcherType.HTTP, True, latency_ms=50.0)

        router._persistent_heap.clear()

        url = "https://perm-new.com/page"
        for _ in range(100):
            router.select(url)
            router.report_result(url, FetcherType.HTTP, True, latency_ms=50.0)

        assert len(router._persistent_rules) <= 3

        print(" 堆空 fallback 逻辑正确")


def test_promotion_early_return():
    """测试 _check_promotion 的早退（覆盖 adaptive_router.py:331）"""
    with tempfile.TemporaryDirectory() as tmpdir:
        router = AdaptiveRouter(rules_file=Path(tmpdir) / "test.pkl")

        router._check_promotion("non-existent-domain.com")

        assert "non-existent-domain.com" not in router._persistent_rules

        print(" _check_promotion 早退逻辑正确")


def test_cleanup_inactive_trigger():
    """测试定期清理触发（覆盖 adaptive_router.py:388-394）"""
    with tempfile.TemporaryDirectory() as tmpdir:
        router = AdaptiveRouter(
            rules_file=Path(tmpdir) / "test.pkl",
            cleanup_interval_minutes=0.001,
            inactive_days=0,
        )

        for i in range(5):
            url = f"https://old{i}.com/page"
            router.select(url)
            router.report_result(url, FetcherType.HTTP, True, latency_ms=50.0)

        time.sleep(0.1)

        router.select("https://trigger.com/page")

        assert len(router._learning_cache) <= 1

        print(" 定期清理触发正确")


def test_async_save_no_event_loop():
    """测试无事件循环时的同步保存 fallback（覆盖 persistence.py:95-97）"""
    with tempfile.TemporaryDirectory() as tmpdir:
        router = AdaptiveRouter(
            rules_file=Path(tmpdir) / "test.pkl",
            save_interval_minutes=0.001,
        )

        for i in range(5):
            router.select(f"https://domain{i}.com/page")
            router.report_result(f"https://domain{i}.com/page", FetcherType.HTTP, True, latency_ms=50.0)

        time.sleep(0.1)

        router._persistence.request_save(router._persistent_rules, router._wildcard_rules)

        time.sleep(0.1)
        router.shutdown()

        rules_file = Path(tmpdir) / "test.pkl"
        assert rules_file.exists()

        print(" 异步保存（含 fallback）正确")


def test_extreme_low_success_rate_cost():
    """测试极低成功率的成本计算（覆盖 cost_learner.py:138-139）"""
    with tempfile.TemporaryDirectory() as tmpdir:
        router = AdaptiveRouter(rules_file=Path(tmpdir) / "test.pkl")

        url = "https://extremely-bad.com/page"

        for _ in range(1000):
            router.report_result(url, FetcherType.HTTP, False, latency_ms=50.0)

        for _ in range(5):
            router.report_result(url, FetcherType.HTTP, True, latency_ms=50.0)

        cost = router._calculate_expected_cost("extremely-bad.com", FetcherType.HTTP)

        assert cost > 1.0

        print(f" 极低成功率成本计算正确（成本={cost:.2f}，含惩罚）")


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
