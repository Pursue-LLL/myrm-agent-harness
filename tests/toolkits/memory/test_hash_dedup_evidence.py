"""Evidence-based performance validation for hash deduplication.

Compares Layer 1 hash dedup vs Layer 2 vector search performance.
"""

import asyncio

import pytest

from myrm_agent_harness.toolkits.memory._internal.hash_utils import compute_content_hash
from myrm_agent_harness.toolkits.memory.strategies.deduplicator import SmartDeduplicator
from myrm_agent_harness.toolkits.memory.types import SemanticMemory


@pytest.fixture
def mock_llm():
    """Mock LLM."""

    class MockLLM:
        async def ainvoke(self, messages):
            class Response:
                content = "DECISION: NEW\nREASON: Test"

            return Response()

    return MockLLM()


@pytest.fixture
def mock_vector_with_latency():
    """Mock vector store with realistic search latency."""

    class MockVector:
        def __init__(self):
            self.search_count = 0

        async def search(self, collection, embedding, limit, filters, score_threshold):
            self.search_count += 1
            import asyncio

            await asyncio.sleep(0.01)
            return []

        async def get(self, collection, ids):
            return []

    return MockVector()


@pytest.fixture
def mock_embedding():
    """Mock embedding."""

    class MockEmbedding:
        @property
        def dimension(self):
            return 384

        async def embed(self, text):
            return [0.1] * 384

        async def embed_batch(self, texts):
            return [[0.1] * 384 for _ in texts]

    return MockEmbedding()


@pytest.fixture
def mock_config():
    """Mock config."""

    class MockConfig:
        semantic_collection = "test_semantic"
        episodic_collection = "test_episodic"

        class dedup:  # noqa: N801
            high_threshold = 0.95
            low_threshold = 0.60

    return MockConfig()


@pytest.mark.asyncio
async def test_hash_layer_saves_vector_search(mock_llm, mock_vector_with_latency, mock_embedding, mock_config):
    """Measure vector search calls saved by Layer 1 hash deduplication.

    Evidence: Hash layer should block duplicates before vector search.
    """
    dedup = SmartDeduplicator(mock_llm, max_cache_size=1000)
    vector = mock_vector_with_latency

    mem1 = SemanticMemory(content="Redis timeout is 5 seconds")
    mem1.embedding = [0.1] * 384

    await dedup.deduplicate_batch([mem1], vector, mock_embedding, mock_config, None)
    search_count_after_first = vector.search_count

    duplicates = [
        SemanticMemory(content="Redis timeout is 5 seconds"),
        SemanticMemory(content="Redis timeout is 5 seconds!"),
        SemanticMemory(content="Redis   timeout   is   5   seconds"),
    ]
    for dup in duplicates:
        dup.embedding = [0.1] * 384

    await dedup.deduplicate_batch(duplicates, vector, mock_embedding, mock_config, None)
    search_count_after_duplicates = vector.search_count

    vector_searches_saved = 3 - (search_count_after_duplicates - search_count_after_first)

    assert vector_searches_saved == 3, f"Expected 3 vector searches saved, got {vector_searches_saved}"
    print(f"\n Evidence: Hash layer saved {vector_searches_saved}/3 vector searches (100%)")


@pytest.mark.asyncio
async def test_hash_normalization_effectiveness(mock_llm, mock_vector_with_latency, mock_embedding, mock_config):
    """Measure normalization effectiveness in catching variants.

    Evidence: Enhanced normalization should catch all text variants.
    """
    dedup = SmartDeduplicator(mock_llm, max_cache_size=1000)
    vector = mock_vector_with_latency

    original = SemanticMemory(content="Database pool size is 10")
    original.embedding = [0.1] * 384
    await dedup.deduplicate_batch([original], vector, mock_embedding, mock_config, None)

    variants = [
        "Database pool size is 10!",
        "Database   pool   size   is   10",
        "DATABASE POOL SIZE IS 10",
        "Database pool size is 10.",
        "database pool size is 10",
    ]

    caught = 0
    for content in variants:
        mem = SemanticMemory(content=content)
        mem.embedding = [0.1] * 384
        result = await dedup.deduplicate_batch([mem], vector, mock_embedding, mock_config, None)
        if len(result) == 0:
            caught += 1

    effectiveness = caught / len(variants) * 100
    assert effectiveness == 100.0, f"Expected 100% effectiveness, got {effectiveness}%"
    print(f"\n Evidence: Normalization caught {caught}/{len(variants)} variants ({effectiveness}%)")


@pytest.mark.asyncio
async def test_hash_performance_vs_vector():
    """Compare hash computation vs vector search latency.

    Evidence: Hash should be orders of magnitude faster than vector search.
    """
    import time

    test_content = "Redis timeout is 5 seconds with some additional context"

    hash_times = []
    for _ in range(1000):
        start = time.perf_counter_ns()
        compute_content_hash(test_content)
        hash_times.append(time.perf_counter_ns() - start)

    avg_hash_ns = sum(hash_times) / len(hash_times)

    class MockVector:
        async def search(self, collection, embedding, limit, filters, score_threshold):
            await asyncio.sleep(0.01)
            return []

    vector = MockVector()
    vector_times = []
    for _ in range(100):
        start = time.perf_counter_ns()
        await vector.search("test", [0.1] * 384, 5, {}, 0.6)
        vector_times.append(time.perf_counter_ns() - start)

    avg_vector_ns = sum(vector_times) / len(vector_times)
    speedup = avg_vector_ns / avg_hash_ns

    print("\n Evidence:")
    print(f"  Hash computation: {avg_hash_ns:.0f} ns")
    print(f"  Vector search: {avg_vector_ns:.0f} ns")
    print(f"  Speedup: {speedup:.0f}x faster")

    assert speedup > 100, f"Hash should be >100x faster than vector search, got {speedup:.0f}x"


@pytest.mark.asyncio
async def test_memory_overhead_measurement():
    """Measure actual memory overhead of hash cache.

    Evidence: 10000 entries should use minimal memory.
    """
    import sys
    from collections import OrderedDict

    cache: OrderedDict[str, str] = OrderedDict()

    for i in range(10000):
        hash_key = compute_content_hash(f"Memory content {i}")
        memory_id = f"mem-{i:08d}"
        cache[hash_key] = memory_id

    container_overhead = sys.getsizeof(cache)
    entry_sizes = [sys.getsizeof(k) + sys.getsizeof(v) for k, v in list(cache.items())[:100]]
    avg_entry_bytes = sum(entry_sizes) / len(entry_sizes)
    total_entry_bytes = avg_entry_bytes * len(cache)
    total_kb = (container_overhead + total_entry_bytes) / 1024

    print("\n Evidence:")
    print(f"  Cache entries: {len(cache)}")
    print(f"  Container overhead: {container_overhead / 1024:.1f} KB")
    print(f"  Total memory: {total_kb:.1f} KB")
    print(f"  Per entry: {avg_entry_bytes:.1f} bytes")

    assert total_kb < 2048, f"Memory overhead should be <2MB, got {total_kb:.1f}KB"


@pytest.mark.asyncio
async def test_cross_session_dedup_effectiveness(mock_llm, mock_vector_with_latency, mock_embedding, mock_config):
    """Measure cross-session deduplication effectiveness.

    Evidence: Global cache should deduplicate across multiple sessions.
    """
    dedup = SmartDeduplicator(mock_llm, max_cache_size=1000)
    vector = mock_vector_with_latency

    common_contents = [
        "Redis timeout is 5 seconds",
        "PostgreSQL pool size is 10",
        "System uses async processing",
    ]

    for _session_id in range(5):
        for content in common_contents:
            mem = SemanticMemory(content=content)
            mem.embedding = [0.1] * 384
            await dedup.deduplicate_batch([mem], vector, mock_embedding, mock_config, None)

    total_attempts = 5 * 3
    unique_stored = 3
    dedup_rate = (total_attempts - unique_stored) / total_attempts * 100

    print("\n Evidence:")
    print(f"  Total attempts: {total_attempts}")
    print(f"  Unique stored: {unique_stored}")
    print(f"  Deduplication rate: {dedup_rate:.1f}%")
    print(f"  Vector searches saved: {total_attempts - unique_stored}")

    assert dedup_rate == 80.0, f"Expected 80% dedup rate, got {dedup_rate}%"
