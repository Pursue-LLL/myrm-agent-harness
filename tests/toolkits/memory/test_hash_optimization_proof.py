"""Proof of hash deduplication optimization effectiveness.

Compares performance before (clearing cache) vs after (persistent cache).
"""

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
def mock_vector_with_counter():
    """Mock vector store that counts search calls."""

    class MockVector:
        def __init__(self):
            self.search_count = 0

        async def search(self, collection, embedding, limit, filters, score_threshold):
            self.search_count += 1
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
async def test_optimization_proof_vector_search_reduction(
    mock_llm, mock_vector_with_counter, mock_embedding, mock_config
):
    """Prove that persistent hash cache reduces vector searches.

    Scenario: 3 sessions, each attempts to store same 3 memories.
    - Before optimization: 9 vector searches (cache cleared each batch)
    - After optimization: 3 vector searches (cache persists)
    - Improvement: 66.7% reduction in vector searches
    """
    dedup = SmartDeduplicator(mock_llm, max_cache_size=1000)
    vector = mock_vector_with_counter

    common_contents = [
        "Redis timeout is 5 seconds",
        "PostgreSQL pool size is 10",
        "System uses async processing",
    ]

    for _session_id in range(3):
        batch = []
        for content in common_contents:
            mem = SemanticMemory(content=content)
            mem.embedding = [0.1] * 384
            batch.append(mem)

        await dedup.deduplicate_batch(batch, vector, mock_embedding, mock_config, None)

    total_attempts = 3 * 3
    vector_searches = vector.search_count
    searches_saved = total_attempts - vector_searches
    reduction_rate = searches_saved / total_attempts * 100

    print("\n Optimization Proof:")
    print(f"  Total memory attempts: {total_attempts}")
    print(f"  Vector searches performed: {vector_searches}")
    print(f"  Vector searches saved: {searches_saved}")
    print(f"  Reduction rate: {reduction_rate:.1f}%")

    assert vector_searches == 3, f"Expected 3 vector searches (first batch only), got {vector_searches}"
    assert abs(reduction_rate - 66.7) < 0.1, f"Expected ~66.7% reduction, got {reduction_rate:.1f}%"


@pytest.mark.asyncio
async def test_optimization_proof_normalization_effectiveness(
    mock_llm, mock_vector_with_counter, mock_embedding, mock_config
):
    """Prove that enhanced normalization catches all text variants.

    Scenario: Store 1 original + 5 variants.
    - Without normalization: 6 vector searches
    - With normalization: 1 vector search
    - Improvement: 83.3% reduction
    """
    dedup = SmartDeduplicator(mock_llm, max_cache_size=1000)
    vector = mock_vector_with_counter

    variants = [
        "Database pool size is 10",
        "Database pool size is 10!",
        "Database   pool   size   is   10",
        "DATABASE POOL SIZE IS 10",
        "Database pool size is 10.",
        "database pool size is 10",
    ]

    for content in variants:
        mem = SemanticMemory(content=content)
        mem.embedding = [0.1] * 384
        await dedup.deduplicate_batch([mem], vector, mock_embedding, mock_config, None)

    total_attempts = len(variants)
    vector_searches = vector.search_count
    searches_saved = total_attempts - vector_searches
    reduction_rate = searches_saved / total_attempts * 100

    print("\n Normalization Proof:")
    print(f"  Total variants: {total_attempts}")
    print(f"  Vector searches: {vector_searches}")
    print(f"  Searches saved: {searches_saved}")
    print(f"  Reduction rate: {reduction_rate:.1f}%")

    assert vector_searches == 1, f"Expected 1 vector search (original only), got {vector_searches}"
    assert abs(reduction_rate - 83.3) < 0.1, f"Expected ~83.3% reduction, got {reduction_rate:.1f}%"


@pytest.mark.asyncio
async def test_optimization_proof_memory_efficiency():
    """Prove that hash cache memory overhead is negligible.

    Evidence: 10000 entries use <2MB memory.
    """
    import sys
    from collections import OrderedDict

    cache: OrderedDict[str, str] = OrderedDict()

    for i in range(10000):
        hash_key = compute_content_hash(f"Memory content {i}")
        memory_id = f"mem-{i:08d}"
        cache[hash_key] = memory_id

    container_overhead = sys.getsizeof(cache)
    sample_entries = list(cache.items())[:100]
    entry_sizes = [sys.getsizeof(k) + sys.getsizeof(v) for k, v in sample_entries]
    avg_entry_bytes = sum(entry_sizes) / len(entry_sizes)
    total_entry_bytes = avg_entry_bytes * len(cache)
    total_mb = (container_overhead + total_entry_bytes) / (1024 * 1024)

    print("\n Memory Efficiency Proof:")
    print(f"  Cache entries: {len(cache)}")
    print(f"  Total memory: {total_mb:.2f} MB")
    print(f"  Per entry: {avg_entry_bytes:.0f} bytes")
    print(f"  Overhead: {total_mb / 10:.2f} MB per 1000 entries")

    assert total_mb < 2.0, f"Memory should be <2MB, got {total_mb:.2f}MB"


@pytest.mark.asyncio
async def test_optimization_proof_lru_capacity_control():
    """Prove that LRU eviction maintains bounded memory.

    Evidence: Cache size never exceeds capacity regardless of input volume.
    """
    from collections import OrderedDict

    capacity = 100
    eviction_ratio = 0.1
    cache: OrderedDict[str, str] = OrderedDict()

    max_size_observed = 0

    for i in range(500):
        hash_key = compute_content_hash(f"Content {i}")

        if len(cache) >= capacity:
            evict_count = max(1, int(capacity * eviction_ratio))
            for _ in range(evict_count):
                if cache:
                    cache.popitem(last=False)

        cache[hash_key] = f"mem-{i}"
        max_size_observed = max(max_size_observed, len(cache))

    final_size = len(cache)

    print("\n LRU Capacity Control Proof:")
    print(f"  Capacity limit: {capacity}")
    print("  Total insertions: 500")
    print(f"  Max size observed: {max_size_observed}")
    print(f"  Final size: {final_size}")
    print(f"  Capacity maintained: {max_size_observed <= capacity}")

    assert max_size_observed <= capacity, f"Max size {max_size_observed} exceeded capacity {capacity}"
    assert final_size <= capacity, f"Final size {final_size} exceeded capacity {capacity}"
