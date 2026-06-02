"""Test final optimizations: OrderedDict, configurable normalization, adaptive capacity."""

import pytest

from myrm_agent_harness.toolkits.memory._internal.hash_utils import NormalizationLevel, compute_normalized_hash
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
def mock_vector():
    """Mock vector store with count support."""

    class MockVector:
        def __init__(self):
            self.memory_count = 500

        async def search(self, collection, embedding, limit, filters, score_threshold):
            return []

        async def get(self, collection, ids):
            return []

        async def count(self, collection, filters):
            return self.memory_count

    return MockVector()


@pytest.fixture
def mock_embedding():
    """Mock embedding."""

    class MockEmbedding:
        async def embed_query(self, text):
            return [0.1] * 384

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
async def test_ordereddict_memory_efficiency():
    """OrderedDict should be more memory-efficient than set+deque."""
    import sys
    from collections import OrderedDict, deque

    n = 10000
    sample_keys = [f"hash_{i:05d}" for i in range(n)]

    cache_ordereddict: OrderedDict[str, None] = OrderedDict()
    for k in sample_keys:
        cache_ordereddict[k] = None

    cache_set: set[str] = set()
    cache_deque: deque[str] = deque(maxlen=n)
    for k in sample_keys:
        cache_set.add(k)
        cache_deque.append(k)

    key_sample_size = sum(sys.getsizeof(k) for k in sample_keys[:100]) / 100
    total_keys_size = key_sample_size * n

    size_ordereddict = sys.getsizeof(cache_ordereddict) + total_keys_size
    size_set_deque = sys.getsizeof(cache_set) + sys.getsizeof(cache_deque) + total_keys_size * 2

    memory_saving = (size_set_deque - size_ordereddict) / size_set_deque * 100
    assert memory_saving > 5, f"OrderedDict should save >5% memory, got {memory_saving:.1f}%"


@pytest.mark.asyncio
async def test_normalization_level_none():
    """NONE level should only match exact content."""
    hash1 = compute_normalized_hash("Redis timeout", NormalizationLevel.NONE)
    hash2 = compute_normalized_hash("Redis timeout!", NormalizationLevel.NONE)
    hash3 = compute_normalized_hash("Redis timeout", NormalizationLevel.NONE)

    assert hash1 != hash2, "NONE level should not normalize punctuation"
    assert hash1 == hash3, "NONE level should match exact content"


@pytest.mark.asyncio
async def test_normalization_level_basic():
    """BASIC level should normalize case and whitespace only."""
    hash1 = compute_normalized_hash("Redis Timeout", NormalizationLevel.BASIC)
    hash2 = compute_normalized_hash("redis   timeout", NormalizationLevel.BASIC)
    hash3 = compute_normalized_hash("Redis timeout!", NormalizationLevel.BASIC)

    assert hash1 == hash2, "BASIC level should normalize case and whitespace"
    assert hash1 != hash3, "BASIC level should not normalize punctuation"


@pytest.mark.asyncio
async def test_normalization_level_full():
    """FULL level should normalize all variants."""
    hash1 = compute_normalized_hash("Redis Timeout!", NormalizationLevel.FULL)
    hash2 = compute_normalized_hash("redis   timeout", NormalizationLevel.FULL)
    hash3 = compute_normalized_hash("Redis timeout.", NormalizationLevel.FULL)

    assert hash1 == hash2 == hash3, "FULL level should normalize all variants"


@pytest.mark.asyncio
async def test_normalization_performance_comparison():
    """Compare performance across normalization levels."""
    import time

    content = "Redis timeout is 5 seconds! This is a longer piece of content with punctuation."
    iterations = 10000

    results = {}
    for level in [NormalizationLevel.NONE, NormalizationLevel.BASIC, NormalizationLevel.FULL]:
        start = time.perf_counter()
        for _ in range(iterations):
            compute_normalized_hash(content, level)
        elapsed = (time.perf_counter() - start) / iterations * 1e9
        results[level.name] = elapsed

    assert results["NONE"] < results["FULL"], (
        f"NONE should be faster than FULL: "
        f"NONE={results['NONE']:.0f}ns, BASIC={results['BASIC']:.0f}ns, FULL={results['FULL']:.0f}ns"
    )

    speedup_basic = results["FULL"] / results["BASIC"]
    speedup_none = results["FULL"] / results["NONE"]
    assert speedup_basic > 0.5, f"BASIC should not be >2x slower than FULL, got {speedup_basic:.1f}x"
    assert speedup_none > 1.2, f"NONE should be >1.2x faster than FULL, got {speedup_none:.1f}x"


@pytest.mark.asyncio
async def test_adaptive_capacity_adjustment(mock_llm, mock_vector, mock_embedding, mock_config):
    """Adaptive capacity should adjust cache size based on memory count."""
    mock_vector.memory_count = 500
    dedup = SmartDeduplicator(mock_llm, max_cache_size=10000, adaptive_capacity=True, capacity_multiplier=1.5)

    for i in range(100):
        mem = SemanticMemory(content=f"Content {i}")
        mem.embedding = [0.1] * 384
        await dedup.deduplicate_batch([mem], mock_vector, mock_embedding, mock_config, None)

    expected_capacity = int(500 * 1.5)
    actual_size = len(dedup._hash_cache)
    assert actual_size <= expected_capacity, f"Cache should adapt to ~{expected_capacity}, got {actual_size}"
    assert actual_size == 100, "Cache should contain all 100 unique entries"


@pytest.mark.asyncio
async def test_adaptive_capacity_disabled(mock_llm, mock_vector, mock_embedding, mock_config):
    """With adaptive disabled, cache should use base capacity."""
    dedup = SmartDeduplicator(mock_llm, max_cache_size=100, adaptive_capacity=False)

    for i in range(150):
        mem = SemanticMemory(content=f"Content {i}")
        mem.embedding = [0.1] * 384
        await dedup.deduplicate_batch([mem], mock_vector, mock_embedding, mock_config, None)

    assert len(dedup._hash_cache) <= 100, "Cache should respect base capacity"
    assert dedup._metrics.evictions == 50, "Should have 50 evictions (150-100)"


@pytest.mark.asyncio
async def test_metrics_tracking(mock_llm, mock_vector, mock_embedding, mock_config):
    """Metrics should accurately track cache operations."""
    dedup = SmartDeduplicator(mock_llm, max_cache_size=10, adaptive_capacity=False)

    for i in range(5):
        mem = SemanticMemory(content=f"Content {i}")
        mem.embedding = [0.1] * 384
        await dedup.deduplicate_batch([mem], mock_vector, mock_embedding, mock_config, None)

    for i in range(3):
        mem = SemanticMemory(content=f"Content {i}")
        mem.embedding = [0.1] * 384
        await dedup.deduplicate_batch([mem], mock_vector, mock_embedding, mock_config, None)

    metrics = dedup.get_metrics()
    assert metrics.total_checks == 8, "Should track all checks"
    assert metrics.cache_hits == 3, "Should track hits"
    assert metrics.cache_misses == 5, "Should track misses"
    assert metrics.hit_rate == 3 / 8, "Hit rate should be accurate"
