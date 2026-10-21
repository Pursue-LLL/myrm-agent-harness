"""测试 LRUCache 内存上限功能"""

from myrm_agent_harness.utils.lru_cache import LRUCache


def test_memory_limit_eviction():
    """测试内存上限驱逐：超过 max_bytes 时驱逐最旧条目"""

    def size_fn(value: str) -> int:
        return len(value.encode("utf-8"))

    cache: LRUCache[str] = LRUCache(maxsize=10, ttl=3600, max_bytes=100, size_fn=size_fn)

    cache.set("key1", "a" * 30)
    cache.set("key2", "b" * 30)
    cache.set("key3", "c" * 30)

    metrics = cache.get_metrics()
    assert metrics["size"] == 3
    assert 85 <= metrics["current_bytes"] <= 95

    cache.set("key4", "d" * 30)

    metrics = cache.get_metrics()
    assert metrics["size"] == 3
    assert 85 <= metrics["current_bytes"] <= 95
    assert metrics["evictions"] == 1

    assert not cache.contains("key1")
    assert cache.contains("key2")
    assert cache.contains("key3")
    assert cache.contains("key4")


def test_memory_limit_with_count_limit():
    """测试内存上限和条目数上限同时生效"""

    def size_fn(value: str) -> int:
        return len(value.encode("utf-8"))

    cache: LRUCache[str] = LRUCache(maxsize=3, ttl=3600, max_bytes=100, size_fn=size_fn)

    cache.set("key1", "a" * 10)
    cache.set("key2", "b" * 10)
    cache.set("key3", "c" * 10)

    metrics = cache.get_metrics()
    assert metrics["size"] == 3
    assert metrics["current_bytes"] < 100

    cache.set("key4", "d" * 10)

    metrics = cache.get_metrics()
    assert metrics["size"] == 3
    assert not cache.contains("key1")


def test_memory_limit_large_single_entry():
    """测试单个条目超过 max_bytes 时的行为"""

    def size_fn(value: str) -> int:
        return len(value.encode("utf-8"))

    cache: LRUCache[str] = LRUCache(maxsize=10, ttl=3600, max_bytes=50, size_fn=size_fn)

    cache.set("small", "x" * 10)
    assert cache.contains("small")

    cache.set("large", "y" * 100)

    metrics = cache.get_metrics()
    assert metrics["size"] == 1
    assert cache.contains("large")
    assert not cache.contains("small")


def test_memory_limit_metrics():
    """测试内存上限相关的 metrics"""

    def size_fn(value: str) -> int:
        return len(value.encode("utf-8"))

    cache: LRUCache[str] = LRUCache(maxsize=10, ttl=3600, max_bytes=100, size_fn=size_fn)

    cache.set("key1", "a" * 30)
    cache.set("key2", "b" * 30)

    metrics = cache.get_metrics()
    assert "max_bytes" in metrics
    assert "byte_utilization" in metrics
    assert metrics["max_bytes"] == 100
    assert 0.5 < metrics["byte_utilization"] < 0.7


def test_no_memory_limit():
    """测试不设置 max_bytes 时的行为（向后兼容）"""

    cache: LRUCache[str] = LRUCache(maxsize=3, ttl=3600)

    cache.set("key1", "a" * 1000)
    cache.set("key2", "b" * 1000)
    cache.set("key3", "c" * 1000)

    metrics = cache.get_metrics()
    assert metrics["size"] == 3
    assert "max_bytes" not in metrics
    assert "byte_utilization" not in metrics

    cache.set("key4", "d" * 1000)
    assert not cache.contains("key1")
