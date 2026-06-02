"""测试 LRUCache 的 stale_hits 指标"""

import time

from myrm_agent_harness.utils.lru_cache import LRUCache


def test_stale_hits_metric():
    """测试 stale_hits 指标统计"""
    cache: LRUCache[str] = LRUCache(maxsize=10, ttl=1)

    cache.set("key1", "value1")

    value, is_expired = cache.get_with_expiry("key1")
    assert value == "value1"
    assert not is_expired

    metrics = cache.get_metrics()
    assert metrics["hits"] == 1
    assert metrics["stale_hits"] == 0
    assert metrics["misses"] == 0

    time.sleep(1.1)

    value, is_expired = cache.get_with_expiry("key1")
    assert value == "value1"
    assert is_expired

    metrics = cache.get_metrics()
    assert metrics["hits"] == 1
    assert metrics["stale_hits"] == 1
    assert metrics["misses"] == 0
    assert metrics["stale_hit_rate"] == 0.5


def test_miss_metric_with_get_with_expiry():
    """测试 get_with_expiry 对不存在的键增加 misses"""
    cache: LRUCache[str] = LRUCache(maxsize=10, ttl=60)

    value, is_expired = cache.get_with_expiry("nonexistent")
    assert value is None
    assert not is_expired

    metrics = cache.get_metrics()
    assert metrics["misses"] == 1
    assert metrics["hits"] == 0
    assert metrics["stale_hits"] == 0


def test_metrics_consistency():
    """测试 metrics 的一致性（hits + misses + stale_hits = total_requests）"""
    cache: LRUCache[str] = LRUCache(maxsize=10, ttl=1)

    cache.set("key1", "value1")
    cache.set("key2", "value2")
    cache.set("key3", "value3")

    # 2 hits
    cache.get_with_expiry("key1")
    cache.get_with_expiry("key2")

    time.sleep(1.1)

    # 2 stale_hits
    cache.get_with_expiry("key1")
    cache.get_with_expiry("key3")

    # 3 misses
    cache.get_with_expiry("key4")
    cache.get_with_expiry("key5")
    cache.get_with_expiry("key6")

    metrics = cache.get_metrics()
    assert metrics["hits"] == 2
    assert metrics["stale_hits"] == 2
    assert metrics["misses"] == 3

    total = metrics["hits"] + metrics["stale_hits"] + metrics["misses"]
    assert total == 7
    assert metrics["hit_rate"] == 2 / 7
    assert metrics["stale_hit_rate"] == 2 / 7
