"""AdaptiveRouter 测试"""

import sys
import tempfile
import time
from pathlib import Path

from myrm_agent_harness.toolkits.web_fetch.fetchers.protocols import FetcherType
from myrm_agent_harness.toolkits.web_fetch.router import AdaptiveRouter
from myrm_agent_harness.toolkits.web_fetch.router.adaptive_router import PersistentRule
from myrm_agent_harness.toolkits.web_fetch.router.domain_metrics import DomainMetricsManager


def _isolated_router(tmpdir: str, **kwargs) -> AdaptiveRouter:
    """Create an AdaptiveRouter with a fresh DomainMetricsManager to avoid global state leakage."""
    return AdaptiveRouter(
        rules_file=Path(tmpdir) / "test.json",
        domain_metrics_manager=DomainMetricsManager(storage_path=Path(tmpdir) / "metrics.json"),
        **kwargs,
    )


def test_basic_routing():
    """测试基本路由功能"""
    print("\n" + "=" * 80)
    print("测试基本路由")
    print("=" * 80)

    with tempfile.TemporaryDirectory() as tmpdir:
        router = _isolated_router(tmpdir)

        # 持久规则
        router._persistent_rules["persistent.com"] = PersistentRule(
            fetcher_type=FetcherType.BROWSER, last_access_time=time.time()
        )
        decision = router.select("https://persistent.com/page")
        print(f" 持久规则: {decision.fetcher_type.name} ({decision.reason})")

        # 学习缓存
        router.report_result("https://learning.com/page", FetcherType.STEALTH, success=True)
        decision = router.select("https://learning.com/page")
        print(f" 学习缓存: {decision.fetcher_type.name} ({decision.reason})")

        # 默认路由
        decision = router.select("https://new.com/page")
        assert decision.fetcher_type == FetcherType.HTTP
        print(f" 默认路由: {decision.fetcher_type.name}")


def test_failure_escalation():
    """测试失败升级"""
    print("\n" + "=" * 80)
    print("测试失败升级")
    print("=" * 80)

    with tempfile.TemporaryDirectory() as tmpdir:
        router = _isolated_router(tmpdir, http_fail_threshold=3, browser_fail_threshold=2)

        url = "https://escalate.com/page"

        # HTTP 失败 3 次
        for i in range(3):
            router.report_result(url, FetcherType.HTTP, success=False)
            print(f"  HTTP 失败 {i + 1}/3")

        decision = router.select(url)
        print(f" HTTP 失败 3 次 → {decision.fetcher_type.name}")
        assert decision.fetcher_type == FetcherType.BROWSER

        # BROWSER 失败 2 次
        for i in range(2):
            router.report_result(url, FetcherType.BROWSER, success=False)
            print(f"  BROWSER 失败 {i + 1}/2")

        decision = router.select(url)
        print(f" BROWSER 失败 2 次 → {decision.fetcher_type.name} ({decision.reason})")
        assert decision.fetcher_type == FetcherType.STEALTH, f"期望 STEALTH，实际 {decision.fetcher_type.name}"


def test_promotion():
    """测试晋升机制"""
    print("\n" + "=" * 80)
    print("测试晋升机制")
    print("=" * 80)

    with tempfile.TemporaryDirectory() as tmpdir:
        router = AdaptiveRouter(
            rules_file=Path(tmpdir) / "test.json",
            promotion_min_count=10,
            promotion_min_success_rate=0.90,
        )

        url = "https://promote.com/page"

        # 10 次成功访问
        for _ in range(10):
            router.report_result(url, FetcherType.BROWSER, success=True)

        # 应该晋升到持久规则
        assert "promote.com" in router._persistent_rules
        assert router._persistent_rules["promote.com"].fetcher_type == FetcherType.BROWSER
        print(" 晋升成功: promote.com → BROWSER")

        # 验证从持久规则读取
        decision = router.select(url)
        print(f" 持久规则命中: {decision.reason}")


def test_exploration():
    """测试探索机制"""
    print("\n" + "=" * 80)
    print("测试探索机制")
    print("=" * 80)

    with tempfile.TemporaryDirectory() as tmpdir:
        # 测试持久规则的探索（使用 50.0 探索率，实际持久规则探索率 = 50.0 / 50 = 1.0）
        router = AdaptiveRouter(
            rules_file=Path(tmpdir) / "test.json",
            exploration_rate=50.0,
        )

        # 添加到持久规则
        router._persistent_rules["explore.com"] = PersistentRule(
            fetcher_type=FetcherType.STEALTH, last_access_time=time.time()
        )

        # 应该降级到 BROWSER（探索率 50.0 / 50.0 = 1.0 = 100%）
        decision = router.select("https://explore.com/page")
        assert decision.fetcher_type == FetcherType.BROWSER
        assert decision.reason == "exploration"
        print(f" 探索降级（持久规则）: STEALTH → {decision.fetcher_type.name}")


def test_demotion():
    """测试降级机制（包括边界场景）"""
    print("\n" + "=" * 80)
    print("测试降级机制")
    print("=" * 80)

    with tempfile.TemporaryDirectory() as tmpdir:
        router = AdaptiveRouter(
            rules_file=Path(tmpdir) / "test.json",
            demotion_fail_count=10,
            demotion_fail_rate=0.3,
            demotion_fail_window_hours=24,
        )

        # 场景 1：高失败率（100%）
        router._persistent_rules["high-fail-rate.com"] = PersistentRule(
            fetcher_type=FetcherType.BROWSER, last_access_time=time.time()
        )
        for _ in range(5):
            router.select("https://high-fail-rate.com/page")
            router.report_result("https://high-fail-rate.com/page", FetcherType.BROWSER, success=False)
        # 5 次失败，失败率 100%，但失败次数 < 10，不应降级（样本不足保护）
        assert "high-fail-rate.com" in router._persistent_rules
        print(" 场景1（超低频高失败率）: 不降级（样本不足）")

        # 场景 2：中频高失败率（修复漏判）
        router._persistent_rules["mid-freq.com"] = PersistentRule(
            fetcher_type=FetcherType.BROWSER, last_access_time=time.time()
        )
        # 20 次访问，8 次失败（40% 失败率）
        for i in range(20):
            router.select("https://mid-freq.com/page")
            success = i >= 12  # 前 8 次失败，后 12 次成功
            router.report_result("https://mid-freq.com/page", FetcherType.BROWSER, success=success)
        # 8 次失败，失败率 40% > 30%，样本数 20 >= 10，应该降级
        assert "mid-freq.com" not in router._persistent_rules
        print(" 场景2（中频高失败率）: 降级成功（修复漏判）")

        # 场景 3：高频大量失败但低失败率
        router._persistent_rules["high-freq.com"] = PersistentRule(
            fetcher_type=FetcherType.STEALTH, last_access_time=time.time()
        )
        # 100 次访问，15 次失败（15% 失败率）
        for i in range(100):
            router.select("https://high-freq.com/page")
            success = i >= 15  # 前 15 次失败
            router.report_result("https://high-freq.com/page", FetcherType.STEALTH, success=success)
        # 15 次失败 >= 10，虽然失败率 15% < 30%，但绝对失败次数达标，应该降级
        assert "high-freq.com" not in router._persistent_rules
        print(" 场景3（高频大量失败）: 降级成功（绝对失败次数）")


def test_max_cache_size():
    """测试缓存大小限制（含高价值保护和强制退缩）"""
    print("\n" + "=" * 80)
    print("测试缓存大小限制")
    print("=" * 80)

    with tempfile.TemporaryDirectory() as tmpdir:
        router = AdaptiveRouter(
            rules_file=Path(tmpdir) / "test.json",
            max_cache_size=50,
            promotion_min_count=100,
        )

        # 场景 1：普通域名（会被退缩）
        for i in range(30):
            url = f"https://normal{i}.com/page"
            router.select(url)
            router.report_result(url, FetcherType.HTTP, success=True)

        # 场景 2：高价值域名（接近晋升，应被保护）
        for i in range(25):
            url = f"https://high-value{i}.com/page"
            for _ in range(60):
                router.select(url)
                router.report_result(url, FetcherType.BROWSER, success=True)

        # 触发缓存上限，高价值域名应被保护
        cache_size = len(router._learning_cache)
        assert cache_size <= 50, f"缓存大小 {cache_size} 超过限制 50"
        assert "high-value0.com" in router._learning_cache, "高价值域名应被保护"
        print(" 高价值保护生效: high-value0.com 被保留")

        # 场景 3：全是高价值时强制退缩
        router2 = AdaptiveRouter(
            rules_file=Path(tmpdir) / "test2.json",
            max_cache_size=10,
            promotion_min_count=100,
        )
        for i in range(15):
            url = f"https://all-high{i}.com/page"
            for _ in range(60):
                router2.select(url)
                router2.report_result(url, FetcherType.HTTP, success=True)

        cache_size = len(router2._learning_cache)
        assert cache_size <= 10, f"强制退缩失败: {cache_size} > 10"
        print(f" 强制退缩生效: {cache_size} <= 10")


def test_wildcard_rules():
    """测试通配符规则匹配"""
    print("\n" + "=" * 80)
    print("测试通配符规则")
    print("=" * 80)

    with tempfile.TemporaryDirectory() as tmpdir:
        router = AdaptiveRouter(rules_file=Path(tmpdir) / "test.json")

        # 添加通配符规则
        router._wildcard_rules["*.example.com"] = FetcherType.BROWSER

        decision = router.select("https://subdomain.example.com/page")
        assert decision.fetcher_type == FetcherType.BROWSER
        print(" 通配符匹配生效: *.example.com → BROWSER")


def test_persistent_rules_limit():
    """测试持久规则上限保护（LRU 退缩）"""
    print("\n" + "=" * 80)
    print("测试持久规则上限")
    print("=" * 80)

    with tempfile.TemporaryDirectory() as tmpdir:
        router = AdaptiveRouter(
            rules_file=Path(tmpdir) / "test.json",
            max_persistent_rules=10,
            promotion_min_count=5,
            promotion_min_success_rate=0.9,
        )

        # 晋升 15 个域名（超过上限 10）
        for i in range(15):
            url = f"https://promote{i}.com/page"
            for _ in range(6):
                router.select(url)
                router.report_result(url, FetcherType.BROWSER, success=True)

        # 应该触发 LRU 退缩
        rules_count = len(router._persistent_rules)
        assert rules_count <= 10, f"持久规则数量 {rules_count} 超过限制 10"
        print(f" LRU 退缩生效: {rules_count} <= 10")


def test_cleanup_inactive():
    """测试定期清理机制"""
    print("\n" + "=" * 80)
    print("测试定期清理")
    print("=" * 80)

    with tempfile.TemporaryDirectory() as tmpdir:
        router = AdaptiveRouter(
            rules_file=Path(tmpdir) / "test.json",
            inactive_days=0,
            cleanup_interval_minutes=0,
        )

        # 添加域名到学习缓存
        router.report_result("https://old-learning.com/page", FetcherType.HTTP, success=True)
        router._learning_cache["old-learning.com"].last_access_time = time.time() - 86400 * 2

        # 添加域名到持久规则
        router._persistent_rules["old-persistent.com"] = PersistentRule(
            fetcher_type=FetcherType.BROWSER, last_access_time=time.time() - 86400 * 2
        )

        # 添加孤立的失败跟踪数据
        router._failure_counters["orphaned.com"][FetcherType.HTTP] = 5

        # 触发清理
        router._cleanup_inactive_domains()

        assert "old-learning.com" not in router._learning_cache
        assert "old-persistent.com" not in router._persistent_rules
        assert "orphaned.com" not in router._failure_counters
        print(" 清理成功: 学习缓存、持久规则、孤立跟踪数据")


def test_persistence():
    """测试持久化（保存/加载/shutdown）"""
    print("\n" + "=" * 80)
    print("测试持久化")
    print("=" * 80)

    with tempfile.TemporaryDirectory() as tmpdir:
        rules_file = Path(tmpdir) / "persistence.json"

        # 创建路由器并添加规则
        router1 = AdaptiveRouter(rules_file=rules_file)
        router1._persistent_rules["persist.com"] = PersistentRule(
            fetcher_type=FetcherType.STEALTH, last_access_time=time.time()
        )
        router1._wildcard_rules["*.wildcard.com"] = FetcherType.BROWSER
        router1.shutdown()
        print(" shutdown 保存成功")

        # 重新加载，验证规则恢复
        router2 = AdaptiveRouter(rules_file=rules_file)
        assert "persist.com" in router2._persistent_rules
        assert router2._persistent_rules["persist.com"].fetcher_type == FetcherType.STEALTH
        assert "*.wildcard.com" in router2._wildcard_rules
        print(" 加载成功: 持久规则和通配符规则恢复")


def test_failure_override():
    """测试失败计数器覆盖持久规则"""
    print("\n" + "=" * 80)
    print("测试失败覆盖")
    print("=" * 80)

    with tempfile.TemporaryDirectory() as tmpdir:
        router = AdaptiveRouter(
            rules_file=Path(tmpdir) / "test.json",
            http_fail_threshold=3,
        )

        # 持久规则为 HTTP（较低级别）
        router._persistent_rules["override.com"] = PersistentRule(
            fetcher_type=FetcherType.HTTP, last_access_time=time.time()
        )

        # HTTP 失败 3 次
        for _ in range(3):
            router.report_result("https://override.com/page", FetcherType.HTTP, success=False)

        # select 应该升级到 BROWSER（失败计数器覆盖持久规则）
        decision = router.select("https://override.com/page")
        assert decision.fetcher_type == FetcherType.BROWSER
        assert decision.reason == "failure_override"
        print(" 失败覆盖生效: 持久规则 HTTP 被升级到 BROWSER")


def test_exploration_http_downgrade():
    """测试探索机制降级到 HTTP"""
    print("\n" + "=" * 80)
    print("测试探索降级（BROWSER → HTTP）")
    print("=" * 80)

    with tempfile.TemporaryDirectory() as tmpdir:
        # 使用 100% 探索率确保触发
        router = AdaptiveRouter(
            rules_file=Path(tmpdir) / "test.json",
            exploration_rate=50.0,
        )

        # 添加 BROWSER 规则
        router._persistent_rules["explore-http.com"] = PersistentRule(
            fetcher_type=FetcherType.BROWSER, last_access_time=time.time()
        )

        # 应该降级到 HTTP（探索率 50.0 / 50.0 = 1.0）
        decision = router.select("https://explore-http.com/page")
        assert decision.fetcher_type == FetcherType.HTTP
        assert decision.reason == "exploration"
        print(" 探索降级: BROWSER → HTTP")


def test_get_stats():
    """测试统计信息获取"""
    print("\n" + "=" * 80)
    print("测试统计信息")
    print("=" * 80)

    with tempfile.TemporaryDirectory() as tmpdir:
        router = AdaptiveRouter(rules_file=Path(tmpdir) / "test.json")

        # 添加数据
        router._persistent_rules["p.com"] = PersistentRule(
            fetcher_type=FetcherType.BROWSER, last_access_time=time.time()
        )
        router._wildcard_rules["*.w.com"] = FetcherType.STEALTH
        router.report_result("https://l.com/page", FetcherType.HTTP, success=True)

        stats = router.get_stats()
        assert stats["persistent_rules"] == 1
        assert stats["wildcard_rules"] == 1
        assert stats["learning_cache"] == 1
        print(f" 统计信息正确: {stats}")


def test_extract_domain_edge_cases():
    """测试域名提取边界情况"""
    print("\n" + "=" * 80)
    print("测试域名提取")
    print("=" * 80)

    with tempfile.TemporaryDirectory() as tmpdir:
        router = AdaptiveRouter(rules_file=Path(tmpdir) / "test.json")

        # 正常 URL
        decision = router.select("https://normal.com/page")
        assert decision.fetcher_type == FetcherType.HTTP

        # 无协议（边界情况）
        decision = router.select("invalid-url")
        assert decision.fetcher_type == FetcherType.HTTP
        print(" 边界情况处理: 无效 URL 不崩溃")


def test_periodic_save():
    """测试定期保存机制"""
    print("\n" + "=" * 80)
    print("测试定期保存")
    print("=" * 80)

    with tempfile.TemporaryDirectory() as tmpdir:
        rules_file = Path(tmpdir) / "auto-save.json"
        router = AdaptiveRouter(
            rules_file=rules_file,
            save_interval_minutes=0,
        )

        # 添加规则
        router._persistent_rules["auto-save.com"] = PersistentRule(
            fetcher_type=FetcherType.BROWSER, last_access_time=time.time()
        )

        # 触发 select 时应自动保存
        router._last_save_time = time.time() - 3600
        router.select("https://test.com/page")

        # 验证文件已保存
        assert rules_file.exists(), "定期保存未触发"

        # 验证内容正确
        router2 = AdaptiveRouter(rules_file=rules_file)
        assert "auto-save.com" in router2._persistent_rules
        print(" 定期保存生效: 规则自动保存到文件")


def test_error_handling():
    """测试异常处理（加载错误、保存错误、域名提取错误）"""
    print("\n" + "=" * 80)
    print("测试异常处理")
    print("=" * 80)

    with tempfile.TemporaryDirectory() as tmpdir:
        # 场景 1：加载损坏的文件
        bad_file = Path(tmpdir) / "bad.json"
        bad_file.write_text("invalid pickle data")
        router = AdaptiveRouter(rules_file=bad_file)
        assert len(router._persistent_rules) == 0
        print(" 加载错误处理: 损坏文件不崩溃")

        # 场景 2：保存到只读目录（模拟保存失败）
        readonly_file = Path("/nonexistent/readonly/test.json")
        router2 = AdaptiveRouter(rules_file=readonly_file)
        router2._persistent_rules["test.com"] = PersistentRule(
            fetcher_type=FetcherType.BROWSER, last_access_time=time.time()
        )
        router2._save_persistent_rules()
        print(" 保存错误处理: 保存失败不崩溃")

        # 场景 3：无效 URL（域名提取异常）
        router3 = AdaptiveRouter(rules_file=Path(tmpdir) / "test3.json")
        decision = router3.select(":::invalid:::")
        assert decision.fetcher_type == FetcherType.HTTP
        print(" 域名提取异常: 无效 URL 不崩溃")


def main():
    """运行所有测试"""
    print("\n" + "=" * 80)
    print("AdaptiveRouter 功能测试")
    print("=" * 80)

    tests = [
        ("基本路由", test_basic_routing),
        ("失败升级", test_failure_escalation),
        ("晋升机制", test_promotion),
        ("探索机制", test_exploration),
        ("降级机制", test_demotion),
        ("缓存大小限制", test_max_cache_size),
        ("通配符规则", test_wildcard_rules),
        ("持久规则上限", test_persistent_rules_limit),
        ("定期清理", test_cleanup_inactive),
        ("持久化", test_persistence),
        ("失败覆盖", test_failure_override),
        ("探索降级HTTP", test_exploration_http_downgrade),
        ("统计信息", test_get_stats),
        ("域名提取", test_extract_domain_edge_cases),
        ("定期保存", test_periodic_save),
        ("异常处理", test_error_handling),
    ]

    passed = 0
    failed = 0

    for name, test_func in tests:
        try:
            if test_func():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"\n 测试 '{name}' 失败: {e}")
            import traceback

            traceback.print_exc()
            failed += 1

    print("\n" + "=" * 80)
    print(f"测试完成: {passed} 通过, {failed} 失败")
    print("=" * 80)

    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
