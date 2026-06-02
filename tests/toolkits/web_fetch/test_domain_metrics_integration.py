"""域名级学习系统集成测试

验证：
1. DomainMetrics 数据模型
2. DomainMetricsManager 持久化
3. CostLearner 域名级学习
4. AdaptiveRouter 失败衰减和自适应探索
5. wait_strategies SMART 策略基于实测数据优化
6. 云沙箱文件锁机制
"""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.web_fetch.fetchers.protocols import FetcherType
from myrm_agent_harness.toolkits.web_fetch.router import (
    AdaptiveRouter,
    DomainMetricsManager,
)
from myrm_agent_harness.toolkits.web_fetch.router.cost_learner import CostLearner
from myrm_agent_harness.toolkits.web_fetch.router.models import DomainMetrics


class TestDomainMetrics:
    """DomainMetrics 数据模型测试"""

    def test_initialization(self):
        """测试初始化和默认值"""
        metrics = DomainMetrics(domain="example.com")

        assert metrics.domain == "example.com"
        assert metrics.total_accesses == 0
        assert metrics.networkidle_success_count == 0
        assert metrics.networkidle_fail_count == 0

        for ft in FetcherType:
            assert ft in metrics.fetcher_latencies
            assert ft in metrics.fetcher_success_counts
            assert ft in metrics.fetcher_total_counts
            assert ft in metrics.failure_timestamps

    def test_record_fetcher_result(self):
        """测试记录 Fetcher 结果"""
        metrics = DomainMetrics(domain="example.com")

        metrics.record_fetcher_result(FetcherType.HTTP, success=True, latency_ms=120.0)

        assert metrics.total_accesses == 1
        assert len(metrics.fetcher_latencies[FetcherType.HTTP]) == 1
        assert metrics.fetcher_latencies[FetcherType.HTTP][0] == 120.0
        assert metrics.fetcher_success_counts[FetcherType.HTTP] == 1
        assert metrics.fetcher_total_counts[FetcherType.HTTP] == 1
        assert metrics.get_success_rate(FetcherType.HTTP) == 1.0

    def test_time_decay_failures(self):
        """测试时间衰减失败计数"""
        metrics = DomainMetrics(domain="example.com")

        now = time.time()
        metrics.failure_timestamps[FetcherType.HTTP].append(now - 25 * 3600)
        metrics.failure_timestamps[FetcherType.HTTP].append(now - 23 * 3600)
        metrics.failure_timestamps[FetcherType.HTTP].append(now - 1 * 3600)

        recent_count = metrics.get_recent_failures_count(FetcherType.HTTP, window_hours=24)
        assert recent_count == 2

    def test_smart_fast_timeout_calculation(self):
        """测试 SMART 策略 fast_timeout 计算"""
        metrics = DomainMetrics(domain="fast.com")

        for _ in range(25):
            metrics.record_networkidle_result(success=True)
            metrics.record_wait_strategy("networkidle", 200)

        timeout = metrics.get_smart_fast_timeout()
        assert timeout is not None
        assert 200 <= timeout <= 500

    def test_smart_fast_timeout_skip_low_success_rate(self):
        """测试低成功率时跳过快速路径"""
        metrics = DomainMetrics(domain="slow.com")

        for _ in range(25):
            metrics.record_networkidle_result(success=False)

        timeout = metrics.get_smart_fast_timeout()
        assert timeout is None


class TestDomainMetricsManager:
    """DomainMetricsManager 持久化和管理测试"""

    def test_local_storage(self):
        """测试本地存储（需要临时解除 pytest 环境检测）"""

        pytest_test = os.environ.pop("PYTEST_CURRENT_TEST", None)

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                storage_path = Path(tmpdir) / "test_metrics.pkl"

                manager = DomainMetricsManager(
                    storage_path=storage_path,
                    use_file_lock=False,
                )

                metrics = manager.get_or_create("example.com")
                metrics.record_fetcher_result(FetcherType.HTTP, success=True, latency_ms=100.0)

                manager._save_metrics()

                manager2 = DomainMetricsManager(
                    storage_path=storage_path,
                    use_file_lock=False,
                )

                loaded_metrics = manager2.get("example.com")
                assert loaded_metrics is not None
                assert loaded_metrics.total_accesses == 1
        finally:
            if pytest_test:
                os.environ["PYTEST_CURRENT_TEST"] = pytest_test

    def test_explicit_file_lock_enable(self):
        """测试显式启用文件锁"""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage_path = Path(tmpdir) / "test_metrics.json"

            manager = DomainMetricsManager(storage_path=storage_path, use_file_lock=True)
            assert manager._use_file_lock is True

    def test_explicit_path_override(self):
        """测试显式路径参数覆盖"""
        with tempfile.TemporaryDirectory() as tmpdir:
            explicit_path = Path(tmpdir) / "custom_metrics.json"
            manager = DomainMetricsManager(storage_path=explicit_path)
            assert manager._storage_path == explicit_path


class TestAdaptiveRouterIntegration:
    """AdaptiveRouter 域名级学习集成测试"""

    def test_domain_level_cost_learning(self):
        """测试域名级成本学习"""
        with tempfile.TemporaryDirectory() as tmpdir:
            rules_path = Path(tmpdir) / "rules.pkl"
            metrics_path = Path(tmpdir) / "metrics.pkl"

            router = AdaptiveRouter(
                rules_file=rules_path,
                domain_metrics_manager=DomainMetricsManager(storage_path=metrics_path),
            )

            router.report_result("https://fast.com/test", FetcherType.HTTP, success=True, latency_ms=50.0)
            router.report_result("https://slow.com/test", FetcherType.HTTP, success=True, latency_ms=500.0)

            metrics_fast = router._domain_metrics_manager.get("fast.com")
            metrics_slow = router._domain_metrics_manager.get("slow.com")

            assert metrics_fast is not None
            assert metrics_slow is not None
            assert metrics_fast.get_average_latency(FetcherType.HTTP) < metrics_slow.get_average_latency(
                FetcherType.HTTP
            )

    def test_adaptive_exploration_rate(self):
        """测试自适应探索率"""
        with tempfile.TemporaryDirectory() as tmpdir:
            rules_path = Path(tmpdir) / "rules.pkl"
            metrics_path = Path(tmpdir) / "metrics.pkl"

            router = AdaptiveRouter(
                rules_file=rules_path,
                exploration_rate=0.05,
                domain_metrics_manager=DomainMetricsManager(storage_path=metrics_path),
            )

            low_freq_domain = "new.com"
            high_freq_domain = "popular.com"

            for _ in range(150):
                router.report_result(f"https://{high_freq_domain}/", FetcherType.HTTP, success=True)

            rate_low = router._get_adaptive_exploration_rate(low_freq_domain)
            rate_high = router._get_adaptive_exploration_rate(high_freq_domain)

            assert rate_low > rate_high

    def test_time_decay_failure_counting(self):
        """测试时间衰减失败计数"""
        with tempfile.TemporaryDirectory() as tmpdir:
            rules_path = Path(tmpdir) / "rules.pkl"
            metrics_path = Path(tmpdir) / "metrics.pkl"

            router = AdaptiveRouter(
                rules_file=rules_path,
                domain_metrics_manager=DomainMetricsManager(storage_path=metrics_path),
            )

            domain = "flaky.com"

            router.report_result(f"https://{domain}/", FetcherType.HTTP, success=False)
            router.report_result(f"https://{domain}/", FetcherType.HTTP, success=False)

            metrics = router._domain_metrics_manager.get(domain)
            assert metrics is not None

            recent_failures = metrics.get_recent_failures_count(FetcherType.HTTP, window_hours=24)
            assert recent_failures == 2


class TestManualIntervention:
    """手动干预接口测试"""

    def test_reset_domain(self):
        """测试重置域名学习数据"""
        router = AdaptiveRouter()

        url = "https://reset.com/test"
        router.report_result(url, FetcherType.HTTP, success=True)
        router.report_result(url, FetcherType.HTTP, success=True)

        assert router.reset_domain(url)

        metrics = router._domain_metrics_manager.get("reset.com")
        assert metrics is None or metrics.total_accesses == 0

    def test_force_fetcher(self):
        """测试强制 Fetcher"""
        router = AdaptiveRouter()

        url = "https://forced.com/test"
        router.force_fetcher(url, FetcherType.STEALTH, ttl_minutes=1)

        decision = router.select(url)
        assert decision.fetcher_type == FetcherType.STEALTH
        assert decision.reason == "forced_override"

    def test_clear_forced_fetcher(self):
        """测试清除强制覆盖"""
        router = AdaptiveRouter()

        url = "https://forced.com/test"
        router.force_fetcher(url, FetcherType.STEALTH, ttl_minutes=1)
        assert router.clear_forced_fetcher(url)

        decision = router.select(url)
        assert decision.fetcher_type == FetcherType.HTTP

    def test_export_import_metrics(self, tmp_path):
        """测试导出导入指标"""
        storage_path1 = tmp_path / "metrics1.json"
        manager = DomainMetricsManager(storage_path=storage_path1)

        metrics = manager.get_or_create("export.com")
        metrics.record_fetcher_result(FetcherType.HTTP, True, 100.0)
        metrics.record_fetcher_result(FetcherType.HTTP, True, 150.0)

        export_file = tmp_path / "metrics_backup.pkl"
        manager.export_metrics(export_file)

        storage_path2 = tmp_path / "metrics2.json"
        manager2 = DomainMetricsManager(storage_path=storage_path2)
        count = manager2.import_metrics(export_file, merge=True)
        assert count == 1

        imported_metrics = manager2.get("export.com")
        assert imported_metrics is not None
        assert imported_metrics.total_accesses == 2


class TestConcurrencySafety:
    """并发安全测试"""

    def test_domain_metrics_concurrent_writes(self):
        """测试 DomainMetrics 并发写入"""
        import threading

        metrics = DomainMetrics(domain="concurrent.com")
        errors = []

        def writer():
            try:
                for _ in range(100):
                    metrics.record_fetcher_result(FetcherType.HTTP, True, 100.0)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert metrics.fetcher_total_counts[FetcherType.HTTP] == 1000


class TestDynamicThresholds:
    """动态阈值测试 — 使用隔离的 DomainMetricsManager 避免受本地持久化数据影响"""

    @staticmethod
    def _isolated_router(tmpdir: str) -> AdaptiveRouter:
        mgr = DomainMetricsManager(storage_path=f"{tmpdir}/metrics.json")
        return AdaptiveRouter(domain_metrics_manager=mgr)

    def test_cost_optimization_threshold_low_frequency(self):
        """测试低频域名成本优化门槛"""
        with tempfile.TemporaryDirectory() as tmpdir:
            router = self._isolated_router(tmpdir)
            metrics = router._domain_metrics_manager.get_or_create("low.com")
            for _ in range(5):
                metrics.record_fetcher_result(FetcherType.HTTP, True)

            threshold = router._get_cost_optimization_threshold("low.com")
            assert threshold == 10

    def test_cost_optimization_threshold_high_frequency(self):
        """测试高频域名成本优化门槛"""
        with tempfile.TemporaryDirectory() as tmpdir:
            router = self._isolated_router(tmpdir)
            metrics = router._domain_metrics_manager.get_or_create("high.com")
            for _ in range(150):
                metrics.record_fetcher_result(FetcherType.HTTP, True)

            threshold = router._get_cost_optimization_threshold("high.com")
            assert threshold == 3

    def test_cost_optimization_threshold_medium_frequency(self):
        """测试中频域名成本优化门槛"""
        with tempfile.TemporaryDirectory() as tmpdir:
            router = self._isolated_router(tmpdir)
            metrics = router._domain_metrics_manager.get_or_create("medium.com")
            for _ in range(50):
                metrics.record_fetcher_result(FetcherType.HTTP, True)

            threshold = router._get_cost_optimization_threshold("medium.com")
            assert 3 < threshold < 10


class TestLatencySeparation:
    """测试成功/失败延迟分离"""

    def test_success_latency_separation(self):
        """测试成功延迟与总延迟分离"""
        metrics = DomainMetrics(domain="test.com")

        metrics.record_fetcher_result(FetcherType.HTTP, success=True, latency_ms=100.0)
        metrics.record_fetcher_result(FetcherType.HTTP, success=True, latency_ms=120.0)
        metrics.record_fetcher_result(FetcherType.HTTP, success=False, latency_ms=5000.0)

        avg_all = metrics.get_average_latency(FetcherType.HTTP)
        avg_success = metrics.get_average_success_latency(FetcherType.HTTP)

        assert avg_all is not None
        assert avg_success is not None
        assert avg_success < avg_all
        assert abs(avg_success - 110.0) < 0.1
        assert len(metrics.fetcher_success_latencies[FetcherType.HTTP]) == 2
        assert len(metrics.fetcher_latencies[FetcherType.HTTP]) == 3

    def test_cost_learner_uses_success_latency(self):
        """测试 CostLearner 使用成功延迟进行成本估计"""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = DomainMetricsManager(storage_path=f"{tmpdir}/metrics.pkl")
            learner = CostLearner(domain_metrics_manager=manager)

            metrics = manager.get_or_create("test.com")
            for _ in range(20):
                metrics.record_fetcher_result(FetcherType.HTTP, success=True, latency_ms=100.0)
            metrics.record_fetcher_result(FetcherType.HTTP, success=False, latency_ms=5000.0)

            cost = learner.estimate_cost(FetcherType.HTTP, domain="test.com")

            assert cost.latency_ms < 200


class TestExpiredForcedFetchers:
    """测试过期强制覆盖自动清理"""

    def test_automatic_cleanup(self):
        """测试定期维护时自动清理过期强制覆盖"""
        router = AdaptiveRouter(cleanup_interval_minutes=0.01)
        router.force_fetcher("test.com", FetcherType.BROWSER, ttl_minutes=0.001)

        assert "test.com" in router._forced_fetchers

        time.sleep(0.1)

        with router._lock.write_lock():
            router._cleanup_expired_forced_fetchers()

        assert "test.com" not in router._forced_fetchers

        decision = router.select("http://test.com/page")
        assert decision.fetcher_type != FetcherType.BROWSER


class TestPerFetcherStats:
    """测试 per-fetcher 统计聚合"""

    def test_per_fetcher_aggregation(self):
        """测试 get_stats 中的 per-fetcher 统计聚合"""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = DomainMetricsManager(storage_path=f"{tmpdir}/metrics.pkl")

            metrics1 = manager.get_or_create("site1.com")
            for _ in range(10):
                metrics1.record_fetcher_result(FetcherType.HTTP, success=True, latency_ms=100.0)
            for _ in range(5):
                metrics1.record_fetcher_result(FetcherType.HTTP, success=False, latency_ms=200.0)

            metrics2 = manager.get_or_create("site2.com")
            for _ in range(8):
                metrics2.record_fetcher_result(FetcherType.HTTP, success=True, latency_ms=150.0)

            stats = manager.get_stats()

            assert "per_fetcher" in stats
            http_stats = stats["per_fetcher"]["HTTP"]
            assert http_stats["total_requests"] == 23
            assert http_stats["success_requests"] == 18
            assert abs(http_stats["success_rate"] - 18 / 23) < 0.01
            assert http_stats["avg_success_latency_ms"] > 0


class TestClearAll:
    """测试 clear_all 接口"""

    def test_clear_all_metrics(self):
        """测试清空所有域名学习数据"""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = DomainMetricsManager(storage_path=f"{tmpdir}/metrics.pkl")

            for i in range(5):
                metrics = manager.get_or_create(f"test{i}.com")
                metrics.record_fetcher_result(FetcherType.HTTP, success=True)

            count = manager.clear_all()

            assert count == 5
            assert len(manager._metrics) == 0


class TestLRUEviction:
    """测试 LRU 驱逐机制"""

    def test_lru_eviction_when_max_domains_exceeded(self):
        """测试超过 max_domains 时 LRU 驱逐最久未访问的域名"""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = DomainMetricsManager(storage_path=f"{tmpdir}/metrics.pkl", max_domains=10)

            for i in range(10):
                metrics = manager.get_or_create(f"domain{i}.com")
                metrics.record_fetcher_result(FetcherType.HTTP, success=True)
                time.sleep(0.01)

            oldest_domain = "domain0.com"
            oldest_metrics = manager.get(oldest_domain)
            assert oldest_metrics is not None

            time.sleep(0.05)
            newest_metrics = manager.get_or_create("domain10.com")
            newest_metrics.record_fetcher_result(FetcherType.HTTP, success=True)

            assert len(manager._metrics) == 10
            assert manager.get(oldest_domain) is None
            assert manager.get("domain1.com") is not None
            assert manager.get("domain10.com") is not None


class TestCleanupInactive:
    """测试清理不活跃域名"""

    def test_cleanup_inactive_domains(self):
        """测试清理 30 天未访问的域名"""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = DomainMetricsManager(storage_path=f"{tmpdir}/metrics.pkl")

            active_metrics = manager.get_or_create("active.com")
            active_metrics.record_fetcher_result(FetcherType.HTTP, success=True)

            inactive_metrics = manager.get_or_create("inactive.com")
            inactive_metrics.last_access = time.time() - 31 * 86400

            assert len(manager._metrics) == 2

            manager.cleanup_inactive_domains()

            assert len(manager._metrics) == 1
            assert manager.get("active.com") is not None
            assert manager.get("inactive.com") is None


class TestFileLock:
    """测试文件锁机制"""

    def test_file_lock_enabled(self):
        """测试文件锁启用时正常工作"""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage_path = f"{tmpdir}/metrics.pkl"
            manager = DomainMetricsManager(storage_path=storage_path, use_file_lock=True)

            assert manager._use_file_lock is True

            metrics = manager.get_or_create("test.com")
            metrics.record_fetcher_result(FetcherType.HTTP, success=True)

            manager._save_metrics()

    def test_file_lock_disabled(self):
        """测试文件锁禁用时正常工作"""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage_path = f"{tmpdir}/metrics.pkl"
            manager = DomainMetricsManager(storage_path=storage_path, use_file_lock=False)

            assert manager._use_file_lock is False

            metrics = manager.get_or_create("test.com")
            metrics.record_fetcher_result(FetcherType.HTTP, success=True)

            manager._save_metrics()


class TestEdgeCases:
    """测试边缘情况"""

    def test_reset_domain_nonexistent(self):
        """测试 reset_domain 不存在的域名返回 False"""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = DomainMetricsManager(storage_path=f"{tmpdir}/metrics.pkl")

            result = manager.reset_domain("nonexistent.com")

            assert result is False

    def test_import_metrics_file_not_found(self):
        """测试 import_metrics 文件不存在返回 0"""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = DomainMetricsManager(storage_path=f"{tmpdir}/metrics.pkl")

            count = manager.import_metrics("/nonexistent/path.pkl")

            assert count == 0

    def test_import_metrics_replace_mode(self):
        """测试 import_metrics 的 merge=False 替换模式"""
        with tempfile.TemporaryDirectory() as tmpdir:
            export_path = f"{tmpdir}/export.pkl"
            import_path = f"{tmpdir}/metrics.pkl"

            manager1 = DomainMetricsManager(storage_path=import_path)
            metrics_old = manager1.get_or_create("old.com")
            metrics_old.record_fetcher_result(FetcherType.HTTP, success=True)

            manager2 = DomainMetricsManager(storage_path=f"{tmpdir}/temp.pkl")
            metrics_new = manager2.get_or_create("new.com")
            metrics_new.record_fetcher_result(FetcherType.BROWSER, success=True)
            manager2.export_metrics(export_path)

            count = manager1.import_metrics(export_path, merge=False)

            assert count == 1
            assert manager1.get("old.com") is None
            assert manager1.get("new.com") is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
