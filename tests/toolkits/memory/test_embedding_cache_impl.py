"""Tests for EmbeddingCache two-tier implementation.

Covers critical paths:
- L1 LRU eviction strategy
- Batch deduplication optimization
- Access count cleanup
- Cache-through behavior
- Statistics tracking
"""

import asyncio

import pytest

from myrm_agent_harness.toolkits.memory._internal.embedding_cache import EmbeddingCache


@pytest.fixture
def mock_embed_func():
    """Create mock single embedding function."""

    async def embed(text: str) -> list[float]:
        return [float(ord(c)) for c in text[:4].ljust(4)]

    return embed


@pytest.fixture
def mock_batch_embed_func():
    """Create mock batch embedding function."""

    async def embed_batch(texts: list[str]) -> list[list[float]]:
        return [[float(ord(c)) for c in t[:4].ljust(4)] for t in texts]

    return embed_batch


class TestL1LRUEviction:
    """Test L1 memory LRU eviction strategy."""

    @pytest.mark.asyncio
    async def test_l1_eviction_on_max_size(self, mock_embed_func):
        """Test L1 evicts oldest item when reaching max_size."""
        cache = EmbeddingCache(embedding_func=mock_embed_func, l1_max_size=3)

        await cache.get_embedding("text1")
        await cache.get_embedding("text2")
        await cache.get_embedding("text3")

        assert len(cache._l1) == 3

        await cache.get_embedding("text4")

        assert len(cache._l1) == 3
        key1 = cache._key("text1")
        assert key1 not in cache._l1
        assert cache._key("text4") in cache._l1

    @pytest.mark.asyncio
    async def test_l1_move_to_end_on_access(self, mock_embed_func):
        """Test L1 moves accessed item to end (most recent)."""
        cache = EmbeddingCache(embedding_func=mock_embed_func, l1_max_size=3)

        await cache.get_embedding("text1")
        await cache.get_embedding("text2")
        await cache.get_embedding("text3")

        await cache.get("text1")

        await cache.get_embedding("text4")

        assert cache._key("text1") in cache._l1
        assert cache._key("text2") not in cache._l1

    @pytest.mark.asyncio
    async def test_l1_access_count_cleanup_on_eviction(self, mock_embed_func):
        """Test access count is cleaned up when L1 item is evicted."""
        cache = EmbeddingCache(embedding_func=mock_embed_func, l1_max_size=2)

        await cache.get_embedding("text1")
        await cache.get_embedding("text2")

        key1 = cache._key("text1")
        assert key1 in cache._access

        await cache.get_embedding("text3")

        assert key1 not in cache._l1
        assert key1 not in cache._access

    @pytest.mark.asyncio
    async def test_l1_concurrent_access_safety(self, mock_embed_func):
        """Test L1 concurrent access is thread-safe."""
        cache = EmbeddingCache(embedding_func=mock_embed_func, l1_max_size=10)

        async def worker(i: int):
            await cache.get_embedding(f"text{i}")

        await asyncio.gather(*[worker(i) for i in range(20)])

        assert len(cache._l1) == 10

    @pytest.mark.asyncio
    async def test_l1_put_updates_existing_key(self, mock_embed_func):
        """Test L1 put updates existing key instead of duplicating."""
        cache = EmbeddingCache(embedding_func=mock_embed_func, l1_max_size=5)

        vec1 = [1.0, 2.0, 3.0]
        vec2 = [4.0, 5.0, 6.0]

        await cache.put("text1", vec1)
        await cache.put("text1", vec2)

        assert len(cache._l1) == 1
        result = await cache.get("text1")
        assert result == vec2

    @pytest.mark.asyncio
    async def test_concurrent_read_write_safety(self, mock_embed_func):
        """Test concurrent reads and writes don't corrupt L1."""
        cache = EmbeddingCache(embedding_func=mock_embed_func, l1_max_size=10)

        async def reader():
            for _ in range(10):
                await cache.get("shared_key")
                await asyncio.sleep(0.001)

        async def writer():
            for i in range(10):
                await cache.put("shared_key", [float(i)])
                await asyncio.sleep(0.001)

        await asyncio.gather(reader(), writer(), reader())

        assert len(cache._l1) <= 10

    @pytest.mark.asyncio
    async def test_concurrent_access_count_accuracy(self, mock_embed_func):
        """Test access count increments correctly under concurrent access."""
        cache = EmbeddingCache(embedding_func=mock_embed_func, l1_max_size=10)

        await cache.put("text1", [1.0, 2.0])

        async def accessor():
            await cache.get("text1")

        await asyncio.gather(*[accessor() for _ in range(10)])

        key = cache._key("text1")
        assert cache._access[key] == 10


class TestBatchDeduplication:
    """Test batch deduplication optimization."""

    @pytest.mark.asyncio
    async def test_batch_deduplication_avoids_duplicate_embeds(self, mock_embed_func):
        """Test batch deduplication avoids duplicate API calls."""
        call_count = 0

        async def counting_embed(text: str) -> list[float]:
            nonlocal call_count
            call_count += 1
            return [float(ord(c)) for c in text[:4].ljust(4)]

        cache = EmbeddingCache(embedding_func=counting_embed, l1_max_size=10)

        texts = ["text1", "text2", "text1", "text3", "text2"]
        result = await cache.get_embeddings_batch(texts)

        assert len(result) == 5
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_batch_empty_input_returns_empty(self, mock_embed_func):
        """Test batch with empty input returns empty list."""
        cache = EmbeddingCache(embedding_func=mock_embed_func, l1_max_size=10)

        result = await cache.get_embeddings_batch([])
        assert result == []

    @pytest.mark.asyncio
    async def test_batch_uses_batch_func_when_available(self, mock_embed_func, mock_batch_embed_func):
        """Test batch uses batch_func when available and len > 1."""
        batch_called = False

        async def tracking_batch(texts: list[str]) -> list[list[float]]:
            nonlocal batch_called
            batch_called = True
            return await mock_batch_embed_func(texts)

        cache = EmbeddingCache(embedding_func=mock_embed_func, batch_func=tracking_batch, l1_max_size=10)

        await cache.get_embeddings_batch(["text1", "text2"])
        assert batch_called

    @pytest.mark.asyncio
    async def test_batch_result_remapping_correctness(self, mock_embed_func):
        """Test batch correctly remaps deduplicated results to original order."""
        cache = EmbeddingCache(embedding_func=mock_embed_func, l1_max_size=10)

        texts = ["a", "b", "a", "c", "b", "a"]
        result = await cache.get_embeddings_batch(texts)

        assert len(result) == 6
        assert result[0] == result[2] == result[5]
        assert result[1] == result[4]


class TestAccessCountCleanup:
    """Test access count cleanup mechanism."""

    @pytest.mark.asyncio
    async def test_access_count_cleanup_triggers_on_threshold(self, mock_embed_func):
        """Test access count cleanup triggers when exceeding threshold."""
        cache = EmbeddingCache(embedding_func=mock_embed_func, l1_max_size=5)

        for i in range(15):
            await cache.get_embedding(f"text{i}")

        assert len(cache._access) <= 5 * 2

    @pytest.mark.asyncio
    async def test_access_count_increments_on_hit(self, mock_embed_func):
        """Test access count increments on cache hit."""
        cache = EmbeddingCache(embedding_func=mock_embed_func, l1_max_size=10)

        await cache.get_embedding("text1")
        key = cache._key("text1")
        assert cache._access[key] == 1

        await cache.get("text1")
        assert cache._access[key] == 2


class TestCacheThroughBehavior:
    """Test cache-through behavior."""

    @pytest.mark.asyncio
    async def test_get_embedding_cache_through_on_miss(self, mock_embed_func):
        """Test get_embedding fetches and caches on miss."""
        cache = EmbeddingCache(embedding_func=mock_embed_func, l1_max_size=10)

        result = await cache.get_embedding("text1")
        assert result is not None

        cached = await cache.get("text1")
        assert cached == result

    @pytest.mark.asyncio
    async def test_batch_cache_through_partial_miss(self, mock_embed_func):
        """Test batch fetches only missing items."""
        call_count = 0

        async def counting_embed(text: str) -> list[float]:
            nonlocal call_count
            call_count += 1
            return [float(ord(c)) for c in text[:4].ljust(4)]

        cache = EmbeddingCache(embedding_func=counting_embed, l1_max_size=10)

        await cache.get_embedding("text1")
        call_count = 0

        result = await cache.get_embeddings_batch(["text1", "text2", "text3"])
        assert len(result) == 3
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_get_batch_calls_get_for_each_text(self, mock_embed_func):
        """Test get_batch calls get for each text."""
        cache = EmbeddingCache(embedding_func=mock_embed_func, l1_max_size=10)

        await cache.put("text1", [1.0, 2.0])
        await cache.put("text2", [3.0, 4.0])

        result = await cache.get_batch(["text1", "text2", "text3"])
        assert len(result) == 3
        assert result[0] == [1.0, 2.0]
        assert result[1] == [3.0, 4.0]
        assert result[2] is None

    @pytest.mark.asyncio
    async def test_put_batch_calls_put_for_each_pair(self, mock_embed_func):
        """Test put_batch calls put for each text/embedding pair."""
        cache = EmbeddingCache(embedding_func=mock_embed_func, l1_max_size=10)

        texts = ["text1", "text2"]
        embeddings = [[1.0, 2.0], [3.0, 4.0]]

        await cache.put_batch(texts, embeddings)

        assert await cache.get("text1") == [1.0, 2.0]
        assert await cache.get("text2") == [3.0, 4.0]


class TestStatisticsTracking:
    """Test statistics tracking."""

    @pytest.mark.asyncio
    async def test_stats_tracks_l1_hits(self, mock_embed_func):
        """Test stats tracks L1 cache hits."""
        cache = EmbeddingCache(embedding_func=mock_embed_func, l1_max_size=10)

        await cache.get_embedding("text1")
        await cache.get("text1")

        stats = cache.get_stats()
        assert stats["l1_hits"] == 1
        assert stats["total"] == 2

    @pytest.mark.asyncio
    async def test_stats_tracks_l2_calls(self, mock_embed_func):
        """Test stats tracks L2 API calls."""
        cache = EmbeddingCache(embedding_func=mock_embed_func, l1_max_size=10)

        await cache.get_embedding("text1")

        stats = cache.get_stats()
        assert stats["l2_calls"] == 1

    @pytest.mark.asyncio
    async def test_stats_calculates_hit_rate(self, mock_embed_func):
        """Test stats calculates hit rate correctly."""
        cache = EmbeddingCache(embedding_func=mock_embed_func, l1_max_size=10)

        await cache.get_embedding("text1")
        await cache.get("text1")
        await cache.get_embedding("text2")

        stats = cache.get_stats()
        assert stats["hit_rate"] == 1 / 3


class TestKeyGeneration:
    """Test cache key generation."""

    @pytest.mark.asyncio
    async def test_key_includes_model_name(self, mock_embed_func):
        """Test key includes model name."""
        cache = EmbeddingCache(embedding_func=mock_embed_func, model_name="test-model", l1_max_size=10)

        key = cache._key("text1")
        assert "test-model" in key

    @pytest.mark.asyncio
    async def test_key_strips_whitespace(self, mock_embed_func):
        """Test key strips leading/trailing whitespace."""
        cache = EmbeddingCache(embedding_func=mock_embed_func, l1_max_size=10)

        key1 = cache._key("  text1  ")
        key2 = cache._key("text1")
        assert key1 == key2
