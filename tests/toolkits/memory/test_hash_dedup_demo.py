"""Comprehensive demo of hash deduplication features."""

import pytest

from myrm_agent_harness.toolkits.memory.config import DeduplicationParams, MemoryConfig
from myrm_agent_harness.toolkits.memory.manager import MemoryManager
from myrm_agent_harness.toolkits.memory.session import MemorySession


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

        async def upsert(self, collection, documents):
            pass

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
def memory_config():
    """Memory configuration."""
    return MemoryConfig(embedding_model="test-model", dedup=DeduplicationParams(enabled=True, hash_cache_capacity=100))


@pytest.mark.asyncio
async def test_complete_dedup_demo(mock_llm, mock_vector, mock_embedding, memory_config):
    """Demonstrate complete two-layer hash deduplication flow.

    Scenario:
    1. Session 1: User discusses Redis configuration
       - Add "Redis timeout is 5 seconds"
       - Add "Redis timeout is 5 seconds!" (session dedup blocks)
       - Add "PostgreSQL pool size is 10"
    2. Session 2: User revisits same topics
       - Add "Redis timeout is 5 seconds" (global dedup blocks)
       - Add "PostgreSQL pool size is 10" (global dedup blocks)
       - Add "New feature: async processing" (allowed)
    3. Session 3: Unicode and whitespace variants
       - Add "café" (allowed)
       - Add "CAFÉ" (global dedup blocks)
       - Add "Redis   timeout   is   5   seconds" (global dedup blocks)
    """
    manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector, embedding=mock_embedding, dedup_llm=mock_llm)

    session1 = MemorySession(manager=manager, chat_id="chat1")
    mem1 = session1.add_knowledge("Redis timeout is 5 seconds")
    mem2 = session1.add_knowledge("Redis timeout is 5 seconds!")
    mem3 = session1.add_knowledge("PostgreSQL pool size is 10")

    assert mem1 is not None, "First unique content should be added"
    assert mem2 is None, "Session layer should block punctuation variant"
    assert mem3 is not None, "Different content should be added"
    assert session1.buffer_size == 2

    stored1 = await session1.flush()
    assert len(stored1) == 2, "Two unique memories stored"

    session2 = MemorySession(manager=manager, chat_id="chat2")
    mem4 = session2.add_knowledge("Redis timeout is 5 seconds")
    mem5 = session2.add_knowledge("PostgreSQL pool size is 10")
    mem6 = session2.add_knowledge("New feature: async processing")

    assert mem4 is not None, "Session layer allows (different session)"
    assert mem5 is not None, "Session layer allows (different session)"
    assert mem6 is not None, "New content allowed"
    assert session2.buffer_size == 3

    stored2 = await session2.flush()
    assert len(stored2) == 1, "Global layer blocks first two, allows third"

    session3 = MemorySession(manager=manager, chat_id="chat3")
    mem7 = session3.add_knowledge("café")
    mem8 = session3.add_knowledge("CAFÉ")
    mem9 = session3.add_knowledge("Redis   timeout   is   5   seconds")

    assert mem7 is not None, "New Unicode content allowed"
    assert mem8 is None, "Session layer blocks case variant"
    assert mem9 is not None, "Session layer allows (different session), but global will block"
    assert session3.buffer_size == 2

    stored3 = await session3.flush()
    assert len(stored3) == 1, "Global layer blocks Redis variant, stores café"

    print("\n=== Hash Deduplication Demo Results ===")
    print("Session 1: 3 attempts → 2 buffered → 2 stored")
    print("Session 2: 3 attempts → 3 buffered → 1 stored (2 global dedup)")
    print("Session 3: 3 attempts → 2 buffered → 1 stored (1 session + 1 global dedup)")
    print("Total: 9 attempts → 4 unique memories stored")
    print(f"Deduplication rate: {(9 - 4) / 9 * 100:.1f}%")


@pytest.mark.asyncio
async def test_fifo_capacity_management_demo(mock_llm, mock_vector, mock_embedding):
    """Demonstrate FIFO eviction with small capacity."""
    config = MemoryConfig(embedding_model="test-model", dedup=DeduplicationParams(enabled=True, hash_cache_capacity=5))

    manager = MemoryManager(config, user_id="test_user", vector=mock_vector, embedding=mock_embedding, dedup_llm=mock_llm)

    for i in range(10):
        session = MemorySession(manager=manager, chat_id=f"chat{i}")
        session.add_knowledge(f"Memory content {i}")
        await session.flush()

    cache_size = len(manager._deduplicator._hash_cache)
    assert cache_size <= 5, f"Cache size {cache_size} should not exceed capacity 5"

    print("\n=== LRU Capacity Management Demo ===")
    print("Added 10 unique memories")
    print("Cache capacity: 5")
    print(f"Final cache size: {cache_size}")
    print(f"Eviction triggered: {10 - cache_size} times")


@pytest.mark.asyncio
async def test_normalization_variants_demo(mock_llm, mock_vector, mock_embedding, memory_config):
    """Demonstrate enhanced normalization catching all variants."""
    manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector, embedding=mock_embedding, dedup_llm=mock_llm)

    variants = [
        ("Original", "Redis timeout is 5 seconds"),
        ("Punctuation", "Redis timeout is 5 seconds!"),
        ("Extra spaces", "Redis   timeout   is   5   seconds"),
        ("Case variant", "REDIS TIMEOUT IS 5 SECONDS"),
        ("Mixed", "Redis Timeout Is 5 Seconds."),
        ("Unicode", "café"),
        ("Unicode variant", "café"),
        ("Unicode case", "CAFÉ"),
    ]

    stored_count = 0
    dedup_count = 0

    for idx, (label, content) in enumerate(variants):
        session = MemorySession(manager=manager, chat_id=f"chat{idx}")
        session.add_knowledge(content)
        stored = await session.flush()
        if len(stored) > 0:
            stored_count += 1
            print(f" {label}: stored")
        else:
            dedup_count += 1
            print(f" {label}: deduplicated")

    print("\n=== Normalization Demo Results ===")
    print(f"Total variants: {len(variants)}")
    print(f"Stored: {stored_count}")
    print(f"Deduplicated: {dedup_count}")
    print(f"Deduplication rate: {dedup_count / len(variants) * 100:.1f}%")

    assert stored_count == 2, "Should store 2 unique contents (Redis + café)"
    assert dedup_count == 6, "Should deduplicate 6 variants"
