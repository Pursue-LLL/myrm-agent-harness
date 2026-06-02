"""Test global hash cache persistence and LRU eviction."""

import pytest

from myrm_agent_harness.toolkits.memory.strategies.deduplicator import SmartDeduplicator
from myrm_agent_harness.toolkits.memory.types import SemanticMemory


@pytest.fixture
def mock_llm():
    """Mock LLM for deduplicator."""

    class MockLLM:
        async def ainvoke(self, messages):
            class Response:
                content = "DECISION: NEW\nREASON: Test"

            return Response()

    return MockLLM()


@pytest.fixture
def mock_vector():
    """Mock vector store."""

    class MockVector:
        async def search(self, collection, embedding, limit, filters, score_threshold):
            return []

        async def get(self, collection, ids):
            return []

    return MockVector()


@pytest.fixture
def mock_embedding():
    """Mock embedding protocol."""

    class MockEmbedding:
        async def embed_query(self, text):
            return [0.1] * 384

    return MockEmbedding()


@pytest.fixture
def mock_config():
    """Mock memory config."""

    class MockConfig:
        semantic_collection = "test_semantic"
        episodic_collection = "test_episodic"

        class dedup:  # noqa: N801
            high_threshold = 0.95
            low_threshold = 0.60

    return MockConfig()


@pytest.mark.asyncio
async def test_hash_cache_persists_across_batches(mock_llm, mock_vector, mock_embedding, mock_config):
    """Hash cache should persist across multiple batches."""
    dedup = SmartDeduplicator(mock_llm, max_cache_size=100, adaptive_capacity=False)

    mem1 = SemanticMemory(content="Redis timeout is 5 seconds")
    mem1.embedding = [0.1] * 384

    batch1 = await dedup.deduplicate_batch([mem1], mock_vector, mock_embedding, mock_config, None)
    assert len(batch1) == 1

    mem2 = SemanticMemory(content="Redis timeout is 5 seconds")
    mem2.embedding = [0.1] * 384

    batch2 = await dedup.deduplicate_batch([mem2], mock_vector, mock_embedding, mock_config, None)
    assert len(batch2) == 0, "Second batch should be deduplicated by hash cache"


@pytest.mark.asyncio
async def test_hash_normalization_variants(mock_llm, mock_vector, mock_embedding, mock_config):
    """Enhanced normalization should catch punctuation and whitespace variants."""
    dedup = SmartDeduplicator(mock_llm, max_cache_size=100, adaptive_capacity=False)

    variants = [
        "Redis timeout is 5 seconds",
        "Redis timeout is 5 seconds!",
        "Redis   timeout   is   5   seconds",
        "redis timeout is 5 seconds",
        "Redis timeout is 5 seconds.",
    ]

    for idx, content in enumerate(variants):
        mem = SemanticMemory(content=content)
        mem.embedding = [0.1] * 384
        result = await dedup.deduplicate_batch([mem], mock_vector, mock_embedding, mock_config, None)
        if idx == 0:
            assert len(result) == 1, "First variant should be stored"
        else:
            assert len(result) == 0, f"Variant {idx} should be deduplicated: {content}"


@pytest.mark.asyncio
async def test_fifo_eviction_on_capacity(mock_llm, mock_vector, mock_embedding, mock_config):
    """FIFO eviction should trigger when capacity exceeded."""
    dedup = SmartDeduplicator(mock_llm, max_cache_size=10, adaptive_capacity=False)

    for i in range(15):
        mem = SemanticMemory(content=f"Memory content {i}")
        mem.embedding = [0.1] * 384
        await dedup.deduplicate_batch([mem], mock_vector, mock_embedding, mock_config, None)

    assert len(dedup._hash_cache) <= 10, "Hash cache size should not exceed capacity"
    assert dedup._metrics.evictions == 5, "Should have 5 evictions (15-10)"


@pytest.mark.asyncio
async def test_fifo_eviction_order(mock_llm, mock_vector, mock_embedding, mock_config):
    """FIFO eviction should remove oldest entries first."""
    dedup = SmartDeduplicator(mock_llm, max_cache_size=5)

    for i in range(1, 6):
        mem = SemanticMemory(content=f"Memory {i}")
        mem.embedding = [0.1] * 384
        await dedup.deduplicate_batch([mem], mock_vector, mock_embedding, mock_config, None)

    assert len(dedup._hash_cache) == 5, "Cache should be at capacity"

    mem_new = SemanticMemory(content="Memory 6")
    mem_new.embedding = [0.1] * 384
    await dedup.deduplicate_batch([mem_new], mock_vector, mock_embedding, mock_config, None)

    from myrm_agent_harness.toolkits.memory._internal.hash_utils import compute_normalized_hash

    first_hash = compute_normalized_hash("Memory 1")
    last_hash = compute_normalized_hash("Memory 6")

    assert first_hash not in dedup._hash_cache, "Oldest entry should be evicted"
    assert last_hash in dedup._hash_cache, "Newest entry should be in cache"


@pytest.mark.asyncio
async def test_unicode_normalization(mock_llm, mock_vector, mock_embedding, mock_config):
    """Unicode variants should normalize to same hash."""
    dedup = SmartDeduplicator(mock_llm, max_cache_size=100)

    variants = [
        "café",
        "café",
        "CAFÉ",
    ]

    for idx, content in enumerate(variants):
        mem = SemanticMemory(content=content)
        mem.embedding = [0.1] * 384
        result = await dedup.deduplicate_batch([mem], mock_vector, mock_embedding, mock_config, None)
        if idx == 0:
            assert len(result) == 1, "First variant should be stored"
        else:
            assert len(result) == 0, f"Unicode variant {idx} should be deduplicated: {content}"
