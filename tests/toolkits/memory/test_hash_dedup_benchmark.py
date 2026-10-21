"""Benchmark hash deduplication performance."""

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
@pytest.mark.benchmark(group="hash_dedup")
async def test_hash_layer_performance(benchmark, mock_llm, mock_vector, mock_embedding, mock_config):
    """Benchmark Layer 1 hash deduplication performance."""
    dedup = SmartDeduplicator(mock_llm, max_cache_size=10000, adaptive_capacity=False)

    memories = [SemanticMemory(content=f"Content {i}") for i in range(100)]
    for mem in memories:
        mem.embedding = [0.1] * 384

    async def run_dedup():
        return await dedup.deduplicate_batch(memories, mock_vector, mock_embedding, mock_config, None)

    result = await benchmark(run_dedup)
    assert len(result) == 100


@pytest.mark.asyncio
@pytest.mark.benchmark(group="hash_dedup")
async def test_hash_hit_performance(benchmark, mock_llm, mock_vector, mock_embedding, mock_config):
    """Benchmark hash cache hit performance (should be O(1))."""
    dedup = SmartDeduplicator(mock_llm, max_cache_size=10000, adaptive_capacity=False)

    mem = SemanticMemory(content="Repeated content")
    mem.embedding = [0.1] * 384
    await dedup.deduplicate_batch([mem], mock_vector, mock_embedding, mock_config, None)

    duplicates = [SemanticMemory(content="Repeated content") for _ in range(100)]
    for dup in duplicates:
        dup.embedding = [0.1] * 384

    async def run_dedup():
        return await dedup.deduplicate_batch(duplicates, mock_vector, mock_embedding, mock_config, None)

    result = await benchmark(run_dedup)
    assert len(result) == 0, "All should be deduplicated"


@pytest.mark.asyncio
@pytest.mark.benchmark(group="hash_dedup")
async def test_normalization_performance(benchmark):
    """Benchmark enhanced normalization overhead."""
    test_content = (
        "Redis timeout is 5 seconds! This is a longer piece of content with punctuation, whitespace, and Unicode: café."
    )

    def run_hash():
        return compute_content_hash(test_content)

    result = benchmark(run_hash)
    assert isinstance(result, str)
    assert len(result) == 16


@pytest.mark.asyncio
@pytest.mark.benchmark(group="hash_dedup")
async def test_fifo_eviction_performance(benchmark, mock_llm, mock_vector, mock_embedding, mock_config):
    """Benchmark FIFO eviction overhead."""
    dedup = SmartDeduplicator(mock_llm, max_cache_size=100, adaptive_capacity=False)

    for i in range(100):
        mem = SemanticMemory(content=f"Initial content {i}")
        mem.embedding = [0.1] * 384
        await dedup.deduplicate_batch([mem], mock_vector, mock_embedding, mock_config, None)

    new_memories = [SemanticMemory(content=f"New content {i}") for i in range(20)]
    for mem in new_memories:
        mem.embedding = [0.1] * 384

    async def run_dedup():
        return await dedup.deduplicate_batch(new_memories, mock_vector, mock_embedding, mock_config, None)

    result = await benchmark(run_dedup)
    assert len(result) == 20
    assert len(dedup._hash_cache) <= 100
