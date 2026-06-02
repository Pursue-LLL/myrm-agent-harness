"""LRUCache 并发安全性测试

LRUCache 现在是纯同步的。在 asyncio 单线程模型中，
纯 CPU 操作不会被中断，天然安全。
这些测试验证在 asyncio.gather 场景下行为正确。
"""

import asyncio
import time

import pytest

from myrm_agent_harness.utils.lru_cache import LRUCache


class TestLRUCacheConcurrency:
    """测试 LRUCache 在 asyncio 并发下的行为"""

    @pytest.mark.asyncio
    async def test_concurrent_set_no_race_condition(self) -> None:
        """验证并发 set 操作无竞态条件"""
        cache: LRUCache[str] = LRUCache(maxsize=100, ttl=3600, id="test")

        async def writer(i: int) -> None:
            for j in range(50):
                cache.set(f"key-{i}-{j}", f"value-{i}-{j}")

        await asyncio.gather(*[writer(i) for i in range(10)])

        assert len(cache) <= 100

    @pytest.mark.asyncio
    async def test_concurrent_get_set_no_corruption(self) -> None:
        """验证并发读写无数据损坏"""
        cache: LRUCache[int] = LRUCache(maxsize=50, ttl=3600, id="test")

        for i in range(20):
            cache.set(f"key-{i}", i)

        results: list[int | None] = []

        async def reader() -> None:
            for i in range(20):
                val = cache.get(f"key-{i}")
                results.append(val)

        async def writer() -> None:
            for i in range(20, 40):
                cache.set(f"key-{i}", i)

        await asyncio.gather(reader(), writer(), reader())

        for val in results:
            assert val is None or isinstance(val, int)

    @pytest.mark.asyncio
    async def test_concurrent_set_no_race(self) -> None:
        """验证并发 set 操作无竞态"""
        cache: LRUCache[str] = LRUCache(maxsize=100, ttl=3600, id="test")

        async def writer(i: int) -> None:
            for j in range(10):
                cache.set(f"key-{i}-{j}", f"value-{i}-{j}")

        await asyncio.gather(*[writer(i) for i in range(5)])

        assert len(cache) == 50

    @pytest.mark.asyncio
    async def test_concurrent_clear_safe(self) -> None:
        """验证并发 clear 操作安全"""
        cache: LRUCache[str] = LRUCache(maxsize=100, ttl=3600, id="test")

        async def writer() -> None:
            for i in range(100):
                cache.set(f"key-{i}", f"value-{i}")
                await asyncio.sleep(0.001)

        async def clearer() -> None:
            await asyncio.sleep(0.05)
            cache.clear()

        await asyncio.gather(writer(), clearer())

        assert len(cache) >= 0

    @pytest.mark.asyncio
    async def test_concurrent_items_safe(self) -> None:
        """验证并发 items 操作安全"""
        cache: LRUCache[str] = LRUCache(maxsize=100, ttl=3600, id="test")

        for i in range(50):
            cache.set(f"key-{i}", f"value-{i}")

        snapshots: list[dict[str, str]] = []

        async def reader() -> None:
            for _ in range(10):
                snapshot = cache.items()
                snapshots.append(snapshot)
                await asyncio.sleep(0.001)

        async def writer() -> None:
            for i in range(50, 100):
                cache.set(f"key-{i}", f"value-{i}")
                await asyncio.sleep(0.001)

        await asyncio.gather(reader(), writer())

        assert len(snapshots) == 10
        for snapshot in snapshots:
            assert isinstance(snapshot, dict)

    @pytest.mark.asyncio
    async def test_metrics_consistency_under_concurrency(self) -> None:
        """验证高并发下 metrics 一致性"""
        cache: LRUCache[str] = LRUCache(maxsize=50, ttl=3600, id="test")

        async def worker(worker_id: int) -> None:
            for i in range(100):
                key = f"key-{i % 50}"
                if i % 2 == 0:
                    cache.set(key, f"value-{worker_id}-{i}")
                else:
                    cache.get(key)

        await asyncio.gather(*[worker(i) for i in range(10)])

        metrics = cache.get_metrics()

        assert metrics["hits"] >= 0
        assert metrics["misses"] >= 0
        assert 0.0 <= metrics["hit_rate"] <= 1.0
        assert metrics["size"] <= 50
        assert metrics["maxsize"] == 50


class TestLRUCacheMetrics:
    """测试 LRUCache metrics 行为"""

    def test_clear_resets_metrics(self) -> None:
        """验证 clear() 重置所有 metrics"""
        cache: LRUCache[str] = LRUCache(maxsize=10, ttl=3600, id="test")

        for i in range(15):
            cache.set(f"key-{i}", f"value-{i}")
        for i in range(10):
            cache.get(f"key-{i}")

        metrics_before = cache.get_metrics()
        assert metrics_before["hits"] > 0 or metrics_before["misses"] > 0
        assert metrics_before["evictions"] > 0

        cache.clear()

        metrics_after = cache.get_metrics()
        assert metrics_after["hits"] == 0
        assert metrics_after["misses"] == 0
        assert metrics_after["evictions"] == 0
        assert metrics_after["expirations"] == 0
        assert metrics_after["size"] == 0

    def test_metrics_utilization(self) -> None:
        """验证 utilization 指标正确"""
        cache: LRUCache[str] = LRUCache(maxsize=10, ttl=3600, id="test")

        for i in range(5):
            cache.set(f"key-{i}", f"value-{i}")

        metrics = cache.get_metrics()
        assert metrics["utilization"] == 0.5

        for i in range(5, 10):
            cache.set(f"key-{i}", f"value-{i}")

        metrics = cache.get_metrics()
        assert metrics["utilization"] == 1.0


class TestLRUCacheEdgeCases:
    """测试 LRUCache 边界情况"""

    @pytest.mark.asyncio
    async def test_concurrent_expiration_cleanup(self) -> None:
        """验证并发过期清理安全"""
        cache: LRUCache[str] = LRUCache(maxsize=100, ttl=1, id="test")

        for i in range(20):
            cache.set(f"key-{i}", f"value-{i}")

        await asyncio.sleep(1.1)

        async def accessor(i: int) -> None:
            cache.get(f"key-{i}")

        await asyncio.gather(*[accessor(i) for i in range(20)])

        assert len(cache) == 0

    @pytest.mark.asyncio
    async def test_concurrent_lru_eviction(self) -> None:
        """验证并发 LRU 驱逐安全"""
        cache: LRUCache[str] = LRUCache(maxsize=10, ttl=3600, id="test")

        async def writer(start: int) -> None:
            for i in range(start, start + 20):
                cache.set(f"key-{i}", f"value-{i}")

        await asyncio.gather(*[writer(i * 20) for i in range(5)])

        assert len(cache) == 10

        metrics = cache.get_metrics()
        assert metrics["evictions"] >= 90

    def test_short_ttl_cleanup(self) -> None:
        """Test lazy cleanup works for short TTL (< 60s)."""
        cache: LRUCache[str] = LRUCache(maxsize=100, ttl=5)

        assert cache._cleanup_interval == 2

        for i in range(50):
            cache.set(f"key-{i}", f"value-{i}")

        initial_size = len(cache)
        assert initial_size == 50

        time.sleep(6)

        cache.set("trigger", "cleanup")

        metrics = cache.get_metrics()
        assert metrics["expirations"] == 50
        assert metrics["size"] == 1

    def test_very_short_ttl_cleanup(self) -> None:
        """Test lazy cleanup works for very short TTL (2s)."""
        cache: LRUCache[str] = LRUCache(maxsize=100, ttl=2)

        assert cache._cleanup_interval == 1

        for i in range(30):
            cache.set(f"key-{i}", f"value-{i}")

        time.sleep(2.5)

        cache.set("trigger", "cleanup")

        metrics = cache.get_metrics()
        assert metrics["expirations"] == 30
        assert metrics["size"] == 1


class TestLRUCacheValidation:
    """测试 LRUCache 参数校验"""

    def test_maxsize_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="maxsize must be positive"):
            LRUCache(maxsize=0, ttl=3600)

        with pytest.raises(ValueError, match="maxsize must be positive"):
            LRUCache(maxsize=-1, ttl=3600)

    def test_ttl_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="ttl must be positive"):
            LRUCache(maxsize=100, ttl=0)

        with pytest.raises(ValueError, match="ttl must be positive"):
            LRUCache(maxsize=100, ttl=-1)
