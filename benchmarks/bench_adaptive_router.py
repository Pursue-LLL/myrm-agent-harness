"""AdaptiveRouter 性能基准测试

验证核心性能特性：
- 异步持久化 vs 同步持久化
- 堆结构 LRU vs 线性扫描
- 成本感知决策 vs 仅成功率决策
"""

import asyncio
import tempfile
import time
from pathlib import Path

from myrm_agent_harness.toolkits.web_fetch.fetchers.protocols import FetcherType
from myrm_agent_harness.toolkits.web_fetch.router.adaptive_router import AdaptiveRouter


async def bench_async_persistence():
    """基准测试：异步持久化性能"""
    with tempfile.TemporaryDirectory() as tmpdir:
        router = AdaptiveRouter(rules_file=Path(tmpdir) / "test.pkl", save_interval_minutes=0)

        domains = [f"domain{i}.com" for i in range(1000)]

        start = time.perf_counter()
        for domain in domains:
            router.report_result(f"https://{domain}", FetcherType.HTTP, True, 100.0)
        elapsed_ms = (time.perf_counter() - start) * 1000

        router.shutdown()

        print(f"异步持久化测试：1000 次 report_result 耗时 {elapsed_ms:.2f}ms")
        print(f"平均单次调用：{elapsed_ms / 1000:.3f}ms")


def bench_heap_lru():
    """基准测试：堆结构 LRU 驱逐性能"""
    with tempfile.TemporaryDirectory() as tmpdir:
        router = AdaptiveRouter(rules_file=Path(tmpdir) / "test.pkl", max_cache_size=100)

        for i in range(200):
            router.report_result(f"https://domain{i}.com", FetcherType.HTTP, True, 100.0)

        eviction_start = time.perf_counter()
        router.report_result("https://trigger-eviction.com", FetcherType.HTTP, True, 100.0)
        eviction_time = (time.perf_counter() - eviction_start) * 1000

        print(f"\n堆结构 LRU 驱逐测试：触发驱逐耗时 {eviction_time:.3f}ms")


def bench_cost_learning():
    """基准测试：多维度成本学习机制"""
    with tempfile.TemporaryDirectory() as tmpdir:
        router = AdaptiveRouter(rules_file=Path(tmpdir) / "test.pkl")

        print("\n多维度成本学习测试：")

        print("  阶段 1（种子成本）：<10 次")
        for i in range(5):
            router.report_result(f"https://test.com/{i}", FetcherType.HTTP, True, 80.0, 1.5, 8.0)
        cost = router._estimate_cost(FetcherType.HTTP)
        print(
            f"    实测 (80ms, 1.5%, 8MB)，估算 ({cost.latency_ms:.1f}ms, {cost.cpu_percent:.1f}%, {cost.memory_mb:.1f}MB)"
        )
        print("    种子 (100ms, 2%, 10MB)")

        print("  阶段 2（渐进学习）：10-99 次")
        for i in range(5, 50):
            router.report_result(f"https://test.com/{i}", FetcherType.HTTP, True, 80.0, 1.5, 8.0)
        cost = router._estimate_cost(FetcherType.HTTP)
        print(f"    50 次实测，估算 ({cost.latency_ms:.1f}ms, {cost.cpu_percent:.1f}%, {cost.memory_mb:.1f}MB)")

        print("  阶段 3（完全信任）：≥100 次")
        for i in range(50, 100):
            router.report_result(f"https://test.com/{i}", FetcherType.HTTP, True, 80.0, 1.5, 8.0)
        cost = router._estimate_cost(FetcherType.HTTP)
        print(
            f"    100 次实测，估算 ({cost.latency_ms:.1f}ms, {cost.cpu_percent:.1f}%, {cost.memory_mb:.1f}MB) — 纯实测"
        )


def bench_decision_throughput():
    """基准测试：决策吞吐量"""
    with tempfile.TemporaryDirectory() as tmpdir:
        router = AdaptiveRouter(rules_file=Path(tmpdir) / "test.pkl")

        for i in range(100):
            router.report_result(f"https://domain{i}.com", FetcherType.HTTP, True, 100.0)

        urls = [f"https://domain{i % 100}.com/page" for i in range(10000)]

        start = time.perf_counter()
        for url in urls:
            router.select(url)
        elapsed = time.perf_counter() - start

        qps = len(urls) / elapsed
        avg_latency_us = (elapsed / len(urls)) * 1_000_000

        print("\n决策吞吐量测试：")
        print(f"  10,000 次决策耗时 {elapsed:.3f}s")
        print(f"  QPS: {qps:,.0f}")
        print(f"  平均延迟: {avg_latency_us:.2f}µs")


if __name__ == "__main__":
    print("=" * 80)
    print("AdaptiveRouter 性能基准测试")
    print("=" * 80)

    asyncio.run(bench_async_persistence())
    bench_heap_lru()
    bench_cost_learning()
    bench_decision_throughput()

    print("\n" + "=" * 80)
    print("测试完成")
    print("=" * 80)
