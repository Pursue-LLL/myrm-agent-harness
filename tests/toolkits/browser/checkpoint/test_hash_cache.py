"""Unit tests for LRUHashCache."""

import time

import pytest

from myrm_agent_harness.toolkits.browser.checkpoint.hash_cache import LRUHashCache


class TestLRUHashCache:
    """Test LRU + TTL hash cache."""

    def test_basic_get_set(self):
        """Test basic get/set operations."""
        cache = LRUHashCache(maxsize=3, ttl=3600)

        cache.set("thread-1", "hash-1")
        result = cache.get("thread-1")
        assert result == "hash-1"

        result = cache.get("thread-2")
        assert result is None

    def test_lru_eviction(self):
        """Test LRU eviction when maxsize is reached."""
        cache = LRUHashCache(maxsize=3, ttl=3600)

        cache.set("thread-1", "hash-1")
        cache.set("thread-2", "hash-2")
        cache.set("thread-3", "hash-3")

        cache.get("thread-1")

        cache.set("thread-4", "hash-4")

        assert cache.get("thread-2") is None
        assert cache.get("thread-1") == "hash-1"
        assert cache.get("thread-3") == "hash-3"
        assert cache.get("thread-4") == "hash-4"

        metrics = cache.get_metrics()
        assert metrics["evictions"] == 1
        assert metrics["size"] == 3
        assert metrics["utilization"] == 1.0

    def test_ttl_expiration(self):
        """Test TTL-based expiration."""
        cache = LRUHashCache(maxsize=10, ttl=1)

        cache.set("thread-1", "hash-1")

        result = cache.get("thread-1")
        assert result == "hash-1"

        time.sleep(1.5)

        result = cache.get("thread-1")
        assert result is None

        metrics = cache.get_metrics()
        assert metrics["expirations"] == 1

    def test_update_existing(self):
        """Test updating existing entry."""
        cache = LRUHashCache(maxsize=3, ttl=3600)

        cache.set("thread-1", "hash-1")
        cache.set("thread-1", "hash-2")

        result = cache.get("thread-1")
        assert result == "hash-2"

        metrics = cache.get_metrics()
        assert metrics["size"] == 1

    def test_delete(self):
        """Test delete operation."""
        cache = LRUHashCache(maxsize=3, ttl=3600)

        cache.set("thread-1", "hash-1")

        deleted = cache.delete("thread-1")
        assert deleted is True

        deleted = cache.delete("thread-2")
        assert deleted is False

        result = cache.get("thread-1")
        assert result is None

    def test_clear(self):
        """Test clear operation and metrics reset."""
        cache = LRUHashCache(maxsize=3, ttl=3600)

        cache.set("thread-1", "hash-1")
        cache.set("thread-2", "hash-2")
        cache.get("thread-1")

        cache.clear()

        assert cache.get("thread-1") is None
        assert cache.get("thread-2") is None

        metrics = cache.get_metrics()
        assert metrics["size"] == 0
        assert metrics["hits"] == 0
        assert metrics["misses"] == 2
        assert metrics["evictions"] == 0
        assert metrics["expirations"] == 0

    def test_metrics(self):
        """Test metrics tracking and utilization."""
        cache = LRUHashCache(maxsize=2, ttl=3600, id="test_cache")

        cache.set("thread-1", "hash-1")
        cache.get("thread-1")
        cache.get("thread-2")

        metrics = cache.get_metrics()
        assert metrics["id"] == "test_cache"
        assert metrics["hits"] == 1
        assert metrics["misses"] == 1
        assert metrics["hit_rate"] == 0.5
        assert metrics["size"] == 1
        assert metrics["maxsize"] == 2
        assert metrics["utilization"] == 0.5

    def test_concurrent_access(self):
        """Test concurrent access (synchronous, safe in asyncio model)."""
        cache = LRUHashCache(maxsize=100, ttl=3600)

        for i in range(50):
            cache.set(f"thread-{i}", f"hash-{i}")
            result = cache.get(f"thread-{i}")
            assert result == f"hash-{i}"

        metrics = cache.get_metrics()
        assert metrics["size"] == 50

    def test_invalid_params(self):
        """Test invalid constructor parameters."""
        with pytest.raises(ValueError, match="maxsize must be positive"):
            LRUHashCache(maxsize=0, ttl=3600)

        with pytest.raises(ValueError, match="ttl must be positive"):
            LRUHashCache(maxsize=10, ttl=-1)

    def test_short_ttl_cleanup(self):
        """Test lazy cleanup works for short TTL (< 60s)."""
        cache = LRUHashCache(maxsize=100, ttl=5)

        assert cache._cleanup_interval == 2

        for i in range(50):
            cache.set(f"thread-{i}", f"hash-{i}")

        initial_size = len(cache._cache)
        assert initial_size == 50

        time.sleep(6)

        cache.set("trigger", "cleanup")

        metrics = cache.get_metrics()
        assert metrics["expirations"] == 50
        assert metrics["size"] == 1

    def test_very_short_ttl_cleanup(self):
        """Test lazy cleanup works for very short TTL (2s)."""
        cache = LRUHashCache(maxsize=100, ttl=2)

        assert cache._cleanup_interval == 1

        for i in range(30):
            cache.set(f"thread-{i}", f"hash-{i}")

        time.sleep(2.5)

        cache.set("trigger", "cleanup")

        metrics = cache.get_metrics()
        assert metrics["expirations"] == 30
        assert metrics["size"] == 1
