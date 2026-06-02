"""Test memory query result caching."""

from __future__ import annotations

import time
from datetime import UTC, datetime

from myrm_agent_harness.toolkits.memory.cache import QueryCache
from myrm_agent_harness.toolkits.memory.types import ConversationMemory, MemorySearchResult, MemoryType


def test_cache_miss() -> None:
    """First access should return None (cache miss)."""
    cache = QueryCache(max_size=100, ttl_seconds=300)
    key = cache.make_key("test query", memory_types=[MemoryType.SEMANTIC], limit=10)

    result = cache.get(key)

    assert result is None
    stats = cache.stats()
    assert stats["hits"] == 0
    assert stats["misses"] == 1


def test_cache_hit() -> None:
    """Second access should return cached results (cache hit)."""
    cache = QueryCache(max_size=100, ttl_seconds=300)
    key = cache.make_key("test query", memory_types=[MemoryType.SEMANTIC], limit=10)

    conv = ConversationMemory(id="conv_1", content="Test", raw_exchange="...", timestamp=datetime.now(UTC))
    results = [MemorySearchResult(memory=conv, score=0.9, memory_type=MemoryType.CONVERSATION)]

    cache.put(key, results)
    cached_results = cache.get(key)

    assert cached_results is not None
    assert len(cached_results) == 1
    assert cached_results[0].memory.id == "conv_1"

    stats = cache.stats()
    assert stats["hits"] == 1


def test_cache_expiration() -> None:
    """Expired entries should return None (cache miss)."""
    cache = QueryCache(max_size=100, ttl_seconds=0.1)
    key = cache.make_key("test query", memory_types=[MemoryType.SEMANTIC], limit=10)

    conv = ConversationMemory(id="conv_1", content="Test", raw_exchange="...", timestamp=datetime.now(UTC))
    results = [MemorySearchResult(memory=conv, score=0.9, memory_type=MemoryType.CONVERSATION)]

    cache.put(key, results)
    time.sleep(0.15)
    cached_results = cache.get(key)

    assert cached_results is None


def test_cache_lru_eviction() -> None:
    """LRU eviction should remove oldest entries when max_size exceeded."""
    cache = QueryCache(max_size=3, ttl_seconds=300)

    for i in range(5):
        key = cache.make_key(f"query_{i}", memory_types=[MemoryType.SEMANTIC], limit=10)
        conv = ConversationMemory(id=f"conv_{i}", content="Test", raw_exchange="...", timestamp=datetime.now(UTC))
        results = [MemorySearchResult(memory=conv, score=0.9, memory_type=MemoryType.CONVERSATION)]
        cache.put(key, results)

    stats = cache.stats()
    assert stats["size"] == 3

    key_0 = cache.make_key("query_0", memory_types=[MemoryType.SEMANTIC], limit=10)
    key_1 = cache.make_key("query_1", memory_types=[MemoryType.SEMANTIC], limit=10)
    key_4 = cache.make_key("query_4", memory_types=[MemoryType.SEMANTIC], limit=10)

    assert cache.get(key_0) is None
    assert cache.get(key_1) is None
    assert cache.get(key_4) is not None


def test_invalidate_all() -> None:
    """Invalidate all should clear all cached entries."""
    cache = QueryCache(max_size=100, ttl_seconds=300)

    for i in range(3):
        key = cache.make_key(f"query_{i}", memory_types=[MemoryType.SEMANTIC], limit=10)
        conv = ConversationMemory(id=f"conv_{i}", content="Test", raw_exchange="...", timestamp=datetime.now(UTC))
        results = [MemorySearchResult(memory=conv, score=0.9, memory_type=MemoryType.CONVERSATION)]
        cache.put(key, results)

    count = cache.invalidate_all()

    assert count == 3
    stats = cache.stats()
    assert stats["size"] == 0


def test_make_key_consistency() -> None:
    """Same parameters should generate same key."""
    cache = QueryCache()

    key1 = cache.make_key("query", memory_types=[MemoryType.SEMANTIC], limit=10, use_rrf=True)
    key2 = cache.make_key("query", memory_types=[MemoryType.SEMANTIC], limit=10, use_rrf=True)

    assert key1 == key2


def test_make_key_different_params() -> None:
    """Different parameters should generate different keys."""
    cache = QueryCache()

    key1 = cache.make_key("query1", memory_types=[MemoryType.SEMANTIC], limit=10)
    key2 = cache.make_key("query2", memory_types=[MemoryType.SEMANTIC], limit=10)
    key3 = cache.make_key("query1", memory_types=[MemoryType.EPISODIC], limit=10)
    key4 = cache.make_key("query1", memory_types=[MemoryType.SEMANTIC], limit=20)

    assert len({key1, key2, key3, key4}) == 4


def test_hit_rate_calculation() -> None:
    """Hit rate should be calculated correctly."""
    import pytest

    cache = QueryCache(max_size=100, ttl_seconds=300)
    key = cache.make_key("query", memory_types=[MemoryType.SEMANTIC], limit=10)

    conv = ConversationMemory(id="conv_1", content="Test", raw_exchange="...", timestamp=datetime.now(UTC))
    results = [MemorySearchResult(memory=conv, score=0.9, memory_type=MemoryType.CONVERSATION)]

    cache.get(key)
    cache.put(key, results)
    cache.get(key)
    cache.get(key)

    stats = cache.stats()
    assert stats["hits"] == 2
    assert stats["misses"] == 1
    assert stats["hit_rate"] == pytest.approx(2.0 / 3.0, rel=0.01)
