"""LRU Cache 工具测试"""

import time

from myrm_agent_harness.utils.lru_cache import LRUCache


class TestLRUCacheBasic:
    """基础功能测试"""

    def test_init_default(self):
        cache: LRUCache[str] = LRUCache()
        assert cache.maxsize == 128
        assert cache.ttl == 3600
        assert len(cache) == 0

    def test_init_custom(self):
        cache: LRUCache[int] = LRUCache(maxsize=10, ttl=60, id="test")
        assert cache.maxsize == 10
        assert cache.ttl == 60
        assert cache.id == "test"

    def test_set_and_get(self):
        cache: LRUCache[str] = LRUCache()
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

    def test_get_method_with_default(self):
        cache: LRUCache[str] = LRUCache()
        assert cache.get("missing", "default") == "default"
        assert cache.get("missing") is None

    def test_contains(self):
        cache: LRUCache[str] = LRUCache()
        cache.set("key1", "value1")
        assert cache.contains("key1")
        assert not cache.contains("missing")

    def test_len(self):
        cache: LRUCache[str] = LRUCache()
        assert len(cache) == 0
        cache.set("k1", "v1")
        assert len(cache) == 1
        cache.set("k2", "v2")
        assert len(cache) == 2

    def test_delete(self):
        cache: LRUCache[str] = LRUCache()
        cache.set("key1", "value1")
        assert cache.contains("key1")
        cache.delete("key1")
        assert not cache.contains("key1")

    def test_clear(self):
        cache: LRUCache[str] = LRUCache()
        cache.set("k1", "v1")
        cache.set("k2", "v2")
        assert len(cache) == 2
        cache.clear()
        assert len(cache) == 0

    def test_items(self):
        cache: LRUCache[str] = LRUCache()
        cache.set("k1", "v1")
        cache.set("k2", "v2")
        items = cache.items()
        assert items == {"k1": "v1", "k2": "v2"}


class TestLRUEviction:
    """LRU淘汰策略测试"""

    def test_eviction_when_full(self):
        cache: LRUCache[int] = LRUCache(maxsize=3)
        cache.set("k1", 1)
        cache.set("k2", 2)
        cache.set("k3", 3)

        cache.set("k4", 4)
        assert not cache.contains("k1")
        assert cache.contains("k2")
        assert cache.contains("k3")
        assert cache.contains("k4")

    def test_lru_order_on_access(self):
        cache: LRUCache[int] = LRUCache(maxsize=3)
        cache.set("k1", 1)
        cache.set("k2", 2)
        cache.set("k3", 3)

        _ = cache.get("k1")

        cache.set("k4", 4)
        assert cache.contains("k1")
        assert not cache.contains("k2")
        assert cache.contains("k3")
        assert cache.contains("k4")

    def test_lru_order_on_update(self):
        cache: LRUCache[int] = LRUCache(maxsize=3)
        cache.set("k1", 1)
        cache.set("k2", 2)
        cache.set("k3", 3)

        cache.set("k1", 10)

        cache.set("k4", 4)
        assert cache.get("k1") == 10
        assert not cache.contains("k2")
        assert cache.contains("k3")
        assert cache.contains("k4")


class TestTTL:
    """TTL过期测试"""

    def test_item_expires_after_ttl(self):
        cache: LRUCache[str] = LRUCache(maxsize=10, ttl=1)
        cache.set("key1", "value1")
        assert cache.contains("key1")

        time.sleep(1.1)

        assert not cache.contains("key1")

    def test_get_expired_returns_default(self):
        cache: LRUCache[str] = LRUCache(maxsize=10, ttl=1)
        cache.set("key1", "value1")

        time.sleep(1.1)

        assert cache.get("key1", "default") == "default"

    def test_getitem_expired_returns_none(self):
        cache: LRUCache[str] = LRUCache(maxsize=10, ttl=1)
        cache.set("key1", "value1")

        time.sleep(1.1)

        assert cache.get("key1") is None

    def test_cleanup_expired_on_set(self):
        cache: LRUCache[str] = LRUCache(maxsize=10, ttl=1)
        cache.set("k1", "v1")
        cache.set("k2", "v2")

        time.sleep(1.6)

        cache.set("k3", "v3")

        assert not cache.contains("k1")
        assert not cache.contains("k2")
        assert cache.contains("k3")


class TestEdgeCases:
    """边界情况测试"""

    def test_maxsize_one(self):
        cache: LRUCache[int] = LRUCache(maxsize=1)
        cache.set("k1", 1)
        cache.set("k2", 2)
        assert not cache.contains("k1")
        assert cache.contains("k2")

    def test_get_missing_returns_none(self):
        cache: LRUCache[str] = LRUCache()
        assert cache.get("missing") is None

    def test_delete_missing_key_silent(self):
        cache: LRUCache[str] = LRUCache()
        cache.delete("missing")

    def test_items_returns_copy(self):
        cache: LRUCache[str] = LRUCache()
        cache.set("k1", "v1")
        items1 = cache.items()
        items2 = cache.items()

        assert items1 is not items2
        assert items1 == items2

    def test_generic_type_int(self):
        cache: LRUCache[int] = LRUCache()
        cache.set("key", 42)
        assert cache.get("key") == 42

    def test_generic_type_dict(self):
        cache: LRUCache[dict[str, str]] = LRUCache()
        cache.set("key", {"a": "b"})
        assert cache.get("key") == {"a": "b"}


class TestIntegration:
    """集成场景测试"""

    def test_mixed_operations(self):
        cache: LRUCache[int] = LRUCache(maxsize=5)

        for i in range(5):
            cache.set(f"k{i}", i)

        assert cache.get("k0") == 0

        cache.set("k0", 100)
        assert cache.get("k0") == 100

        cache.delete("k1")
        assert not cache.contains("k1")

        cache.set("k5", 5)
        assert len(cache) == 5

    def test_lru_with_ttl_interaction(self):
        cache: LRUCache[str] = LRUCache(maxsize=2, ttl=10)

        cache.set("k1", "v1")
        cache.set("k2", "v2")

        cache.set("k3", "v3")
        assert not cache.contains("k1")
        assert cache.contains("k2")
        assert cache.contains("k3")

        short_cache: LRUCache[str] = LRUCache(maxsize=5, ttl=1)
        short_cache.set("expired_key", "value")
        assert short_cache.contains("expired_key")

        time.sleep(1.2)
        assert not short_cache.contains("expired_key")
