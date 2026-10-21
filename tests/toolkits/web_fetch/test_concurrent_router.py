"""AdaptiveRouter 并发安全测试

验证读写锁实现的并发安全性。
"""

import tempfile
import threading
import time
from collections import Counter
from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.web_fetch.router.adaptive_router import (
    AdaptiveRouter,
    FetcherType,
)

pytestmark = pytest.mark.xdist_group("concurrent_router")


def test_concurrent_select_reads():
    """测试多线程并发 select（纯读操作）的安全性和性能"""
    print("\n" + "=" * 80)
    print("测试并发 select（纯读）")
    print("=" * 80)

    with tempfile.TemporaryDirectory() as tmpdir:
        router = AdaptiveRouter(rules_file=Path(tmpdir) / "test.pkl")

        # 预热：建立一些学习数据
        for i in range(10):
            url = f"https://example{i}.com/page"
            router.select(url)
            router.report_result(url, FetcherType.HTTP, success=True, latency_ms=50.0)

        # 并发读：100 个线程同时 select
        thread_count = 100
        iterations_per_thread = 100
        results: list[list[str]] = [[] for _ in range(thread_count)]
        errors: list[Exception] = []

        def worker(thread_id: int):
            try:
                for i in range(iterations_per_thread):
                    url = f"https://example{i % 10}.com/page{i}"
                    decision = router.select(url)
                    results[thread_id].append(decision.reason)
            except Exception as e:
                errors.append(e)

        start_time = time.time()
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(thread_count)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        elapsed = time.time() - start_time

        # 验证：没有异常
        assert len(errors) == 0, f"并发读出现异常: {errors}"

        # 验证：所有线程都完成了 iterations_per_thread 次 select
        total_selects = sum(len(r) for r in results)
        assert total_selects == thread_count * iterations_per_thread

        # 性能：计算 QPS
        qps = total_selects / elapsed
        print(f" 并发读安全: {thread_count} 线程 × {iterations_per_thread} 次 = {total_selects:,} 次调用")
        print(f" 耗时: {elapsed:.3f}s")
        print(f" QPS: {qps:,.0f} (预期 > 30k)")

    # Under xdist parallel load, CPU contention lowers throughput significantly.
    assert qps > 2_000, f"并发 QPS {qps:,.0f} 过低"


def test_concurrent_select_and_report():
    """测试 select（读）和 report_result（写）并发的正确性"""
    print("\n" + "=" * 80)
    print("测试并发 select + report（读写混合）")
    print("=" * 80)

    with tempfile.TemporaryDirectory() as tmpdir:
        router = AdaptiveRouter(rules_file=Path(tmpdir) / "test.pkl")

        thread_count = 50
        iterations_per_thread = 100
        select_counts = Counter()
        report_counts = Counter()
        errors: list[Exception] = []
        lock = threading.Lock()

        def reader_worker(thread_id: int):
            """只读线程"""
            try:
                for i in range(iterations_per_thread):
                    url = f"https://site{i % 5}.com/page"
                    router.select(url)
                    with lock:
                        select_counts[thread_id] += 1
            except Exception as e:
                errors.append(e)

        def writer_worker(thread_id: int):
            """写线程"""
            try:
                for i in range(iterations_per_thread):
                    url = f"https://site{i % 5}.com/page"
                    fetcher = FetcherType.HTTP if i % 2 == 0 else FetcherType.BROWSER
                    router.report_result(url, fetcher, success=True, latency_ms=50.0 + i)
                    with lock:
                        report_counts[thread_id] += 1
            except Exception as e:
                errors.append(e)

        # 启动混合线程：25 个读线程 + 25 个写线程
        start_time = time.time()
        threads = []
        for i in range(thread_count // 2):
            threads.append(threading.Thread(target=reader_worker, args=(i,)))
            threads.append(threading.Thread(target=writer_worker, args=(i + thread_count // 2,)))

        for t in threads:
            t.start()
        for t in threads:
            t.join()
        elapsed = time.time() - start_time

        # 验证：没有异常
        assert len(errors) == 0, f"并发读写出现异常: {errors}"

        # 验证：所有操作都完成
        total_selects = sum(select_counts.values())
        total_reports = sum(report_counts.values())
        expected_ops = (thread_count // 2) * iterations_per_thread

        assert total_selects == expected_ops, f"select 次数不匹配: {total_selects} != {expected_ops}"
        assert total_reports == expected_ops, f"report 次数不匹配: {total_reports} != {expected_ops}"

        # 验证：数据一致性（学习历史应有数据，考虑 deque maxlen=1000 限制）
        total_latency_samples = sum(len(router._latency_history[ft]) for ft in FetcherType)
        expected_samples = min(total_reports, 1000 * len(FetcherType))  # maxlen=1000/fetcher
        assert total_latency_samples > 0, "成本学习数据为空"
        assert total_latency_samples <= expected_samples, "成本学习数据超过限制"

        print(f" 并发读写安全: {thread_count} 线程")
        print(f" Select 操作: {total_selects:,} 次")
        print(f" Report 操作: {total_reports:,} 次")
        print(f" 耗时: {elapsed:.3f}s")
        print(f" 数据一致性: {total_latency_samples} 样本")


def test_concurrent_report_writes():
    """测试多线程并发 report（写操作）的数据一致性"""
    print("\n" + "=" * 80)
    print("测试并发 report（写入）")
    print("=" * 80)

    with tempfile.TemporaryDirectory() as tmpdir:
        router = AdaptiveRouter(rules_file=Path(tmpdir) / "test.pkl")

        thread_count = 50
        reports_per_thread = 100
        errors: list[Exception] = []

        def worker(thread_id: int):
            try:
                for i in range(reports_per_thread):
                    url = f"https://site{thread_id % 10}.com/page{i}"
                    fetcher = FetcherType.HTTP if i % 3 == 0 else FetcherType.BROWSER
                    router.report_result(
                        url,
                        fetcher,
                        success=(i % 5 != 0),
                        latency_ms=50.0 + i,
                        cpu_percent=2.0 + (i % 10),
                        memory_mb=10.0 + (i % 50),
                    )
            except Exception as e:
                errors.append(e)

        start_time = time.time()
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(thread_count)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        elapsed = time.time() - start_time

        # 验证：没有异常
        assert len(errors) == 0, f"并发写出现异常: {errors}"

        # 验证：数据完整性
        total_expected_reports = thread_count * reports_per_thread
        total_latency = sum(len(router._latency_history[ft]) for ft in FetcherType)
        total_cpu = sum(len(router._cpu_history[ft]) for ft in FetcherType)
        total_memory = sum(len(router._memory_history[ft]) for ft in FetcherType)

        print(f" 并发写安全: {thread_count} 线程 × {reports_per_thread} 次")
        print(f" 预期操作: {total_expected_reports:,} 次")
        print(f" 实际样本: latency={total_latency:,}, cpu={total_cpu:,}, memory={total_memory:,}")
        print(f" 耗时: {elapsed:.3f}s")

        # 数据完整性：考虑 deque maxlen=1000/fetcher 的限制
        max_per_fetcher = 1000
        max_total_samples = max_per_fetcher * len(FetcherType)

        assert total_latency > 0, "延迟样本为空"
        assert total_cpu > 0, "CPU 样本为空"
        assert total_memory > 0, "内存样本为空"

        assert total_latency <= max_total_samples, f"延迟样本超限: {total_latency}"
        assert total_cpu <= max_total_samples, f"CPU 样本超限: {total_cpu}"
        assert total_memory <= max_total_samples, f"内存样本超限: {total_memory}"

        # 三个维度样本数应该一致
        assert total_latency == total_cpu == total_memory, "多维度样本数不一致"

        # 验证学习缓存一致性
        cache_size = len(router._learning_cache)
        assert cache_size > 0, "学习缓存为空"
        print(f" 学习缓存: {cache_size} 个域名")


def test_read_write_contention():
    """测试读写竞争场景下的正确性和性能"""
    print("\n" + "=" * 80)
    print("测试读写竞争")
    print("=" * 80)

    with tempfile.TemporaryDirectory() as tmpdir:
        router = AdaptiveRouter(rules_file=Path(tmpdir) / "test.pkl")

        # 预热
        for i in range(10):
            url = f"https://site{i}.com/page"
            router.select(url)
            router.report_result(url, FetcherType.HTTP, success=True, latency_ms=50.0)

        read_threads = 80
        write_threads = 20
        iterations = 200
        errors: list[Exception] = []

        def read_worker():
            try:
                for i in range(iterations):
                    url = f"https://site{i % 10}.com/page{i}"
                    router.select(url)
            except Exception as e:
                errors.append(e)

        def write_worker():
            try:
                for i in range(iterations):
                    url = f"https://site{i % 10}.com/page{i}"
                    router.report_result(url, FetcherType.HTTP, success=True, latency_ms=60.0 + i)
            except Exception as e:
                errors.append(e)

        start_time = time.time()
        threads = []
        for _ in range(read_threads):
            threads.append(threading.Thread(target=read_worker))
        for _ in range(write_threads):
            threads.append(threading.Thread(target=write_worker))

        for t in threads:
            t.start()
        for t in threads:
            t.join()
        elapsed = time.time() - start_time

        # 验证：没有异常
        assert len(errors) == 0, f"读写竞争出现异常: {errors}"

        total_ops = (read_threads + write_threads) * iterations
        qps = total_ops / elapsed

        print(f" 读写竞争安全: {read_threads} 读线程 + {write_threads} 写线程")
        print(f" 总操作: {total_ops:,} 次")
        print(f" 耗时: {elapsed:.3f}s")
        print(f" QPS: {qps:,.0f}")

    # Under xdist parallel load, CPU contention lowers throughput significantly.
    assert qps > 2_000, f"读写竞争 QPS {qps:,.0f} 过低"


def test_data_race_detection():
    """测试数据竞争检测：验证 select 和 report 在极端并发下的数据一致性"""
    print("\n" + "=" * 80)
    print("测试数据竞争检测")
    print("=" * 80)

    with tempfile.TemporaryDirectory() as tmpdir:
        router = AdaptiveRouter(
            rules_file=Path(tmpdir) / "test.pkl",
            promotion_min_count=10000,
        )

        thread_count = 50
        iterations = 30
        errors: list[Exception] = []
        domain = "race-test.com"

        def worker():
            try:
                for i in range(iterations):
                    url = f"https://{domain}/page{i}"
                    decision = router.select(url)
                    time.sleep(0.0001)  # 模拟真实场景的微小延迟
                    router.report_result(
                        url,
                        decision.fetcher_type,
                        success=True,
                        latency_ms=50.0 + i,
                    )
            except Exception as e:
                errors.append(e)

        start_time = time.time()
        threads = [threading.Thread(target=worker) for _ in range(thread_count)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        elapsed = time.time() - start_time

        # 验证：没有异常
        assert len(errors) == 0, f"数据竞争出现异常: {errors}"

        # 验证：数据一致性
        if domain in router._learning_cache:
            stats = router._learning_cache[domain]
            expected_attempts = thread_count * iterations
            assert stats.total_attempts == expected_attempts, (
                f"访问计数不一致: {stats.total_attempts} != {expected_attempts}"
            )
            assert stats.successful_attempts == expected_attempts, "成功计数不一致"
            print(f" 数据一致性: {stats.total_attempts:,} 次访问，{stats.successful_attempts:,} 次成功")

        # 验证：成本学习数据（考虑 deque maxlen=1000/fetcher 限制）
        total_samples = sum(len(router._latency_history[ft]) for ft in FetcherType)
        max_samples = 1000 * len(FetcherType)

        assert total_samples > 0, "成本学习数据为空"
        assert total_samples <= max_samples, f"成本学习数据超限: {total_samples} > {max_samples}"

        print(f" 数据竞争测试通过: {thread_count} 线程 × {iterations} 次")
        print(f" 耗时: {elapsed:.3f}s")
        print(f" 成本样本: {total_samples:,} 条")


def test_shutdown_during_operations():
    """测试运行中调用 shutdown 的安全性"""
    print("\n" + "=" * 80)
    print("测试运行中 shutdown")
    print("=" * 80)

    with tempfile.TemporaryDirectory() as tmpdir:
        router = AdaptiveRouter(rules_file=Path(tmpdir) / "test.pkl")

        thread_count = 20
        iterations = 100
        errors: list[Exception] = []
        shutdown_triggered = threading.Event()

        def worker():
            try:
                for i in range(iterations):
                    if shutdown_triggered.is_set():
                        break
                    url = f"https://site{i % 5}.com/page{i}"
                    decision = router.select(url)
                    router.report_result(url, decision.fetcher_type, success=True, latency_ms=50.0)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(thread_count)]
        for t in threads:
            t.start()

        time.sleep(0.3)
        shutdown_triggered.set()
        router.shutdown()

        for t in threads:
            t.join(timeout=2.0)

        # 验证：shutdown 不应该导致异常（可能有操作被中断，但不应该崩溃）
        print(f" 运行中 shutdown: {len(errors)} 个异常")
        print(f" 持久规则已保存: {len(router._persistent_rules)} 条")

        # 允许少量异常（如已关闭的 router 拒绝操作），但不应该有严重错误
        assert len(errors) < thread_count * 0.5, "shutdown 期间异常过多"


if __name__ == "__main__":
    test_concurrent_select_reads()
    test_concurrent_select_and_report()
    test_concurrent_report_writes()
    test_read_write_contention()
    test_data_race_detection()
    test_shutdown_during_operations()
    print("\n" + "=" * 80)
    print(" 所有并发测试通过")
    print("=" * 80)
