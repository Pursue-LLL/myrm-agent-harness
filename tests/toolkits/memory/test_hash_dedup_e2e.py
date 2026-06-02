"""End-to-end test for hash deduplication across session and global layers."""

import pytest

from myrm_agent_harness.toolkits.memory.config import DeduplicationParams, MemoryConfig
from myrm_agent_harness.toolkits.memory.manager import MemoryManager
from myrm_agent_harness.toolkits.memory.session import MemorySession


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

        async def upsert(self, collection, documents):
            pass

    return MockVector()


@pytest.fixture
def mock_embedding():
    """Mock embedding protocol."""

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
    """Memory configuration with hash dedup enabled."""
    return MemoryConfig(embedding_model="test-model", dedup=DeduplicationParams(enabled=True, hash_cache_capacity=100))


@pytest.mark.asyncio
async def test_session_layer_blocks_duplicates(mock_llm, mock_vector, mock_embedding, memory_config):
    """Session layer should block duplicates before reaching global layer."""
    manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector, embedding=mock_embedding, dedup_llm=mock_llm)
    session = MemorySession(manager=manager, chat_id="chat1")

    mem1 = session.add_knowledge("Redis timeout is 5 seconds")
    mem2 = session.add_knowledge("Redis timeout is 5 seconds!")
    mem3 = session.add_knowledge("Redis   timeout   is   5   seconds")

    assert mem1 is not None
    assert mem2 is None, "Session layer should block punctuation variant"
    assert mem3 is None, "Session layer should block whitespace variant"
    assert session.buffer_size == 1

    stored = await session.flush()
    assert len(stored) == 1


@pytest.mark.asyncio
async def test_global_layer_blocks_cross_session_duplicates(mock_llm, mock_vector, mock_embedding, memory_config):
    """Global layer should block duplicates across different sessions."""
    manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector, embedding=mock_embedding, dedup_llm=mock_llm)

    session1 = MemorySession(manager=manager, chat_id="chat1")
    mem1 = session1.add_knowledge("PostgreSQL pool size is 10")
    assert mem1 is not None
    stored1 = await session1.flush()
    assert len(stored1) == 1

    session2 = MemorySession(manager=manager, chat_id="chat2")
    mem2 = session2.add_knowledge("PostgreSQL pool size is 10")
    assert mem2 is not None, "Session layer should allow (different session)"
    stored2 = await session2.flush()
    assert len(stored2) == 0, "Global layer should block cross-session duplicate"


@pytest.mark.asyncio
async def test_two_layer_dedup_flow(mock_llm, mock_vector, mock_embedding, memory_config):
    """Test complete two-layer flow: session → global."""
    manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector, embedding=mock_embedding, dedup_llm=mock_llm)

    session1 = MemorySession(manager=manager, chat_id="chat1")
    session1.add_knowledge("System uses async processing")
    session1.add_knowledge("System uses async processing!")
    session1.add_knowledge("Database timeout is 30s")
    stored1 = await session1.flush()
    assert len(stored1) == 2, "Session layer should deduplicate first two"

    session2 = MemorySession(manager=manager, chat_id="chat2")
    session2.add_knowledge("System uses async processing")
    session2.add_knowledge("Database timeout is 30s")
    session2.add_knowledge("New feature added")
    stored2 = await session2.flush()
    assert len(stored2) == 1, "Global layer should block first two, allow third"


@pytest.mark.asyncio
async def test_session_isolation(mock_llm, mock_vector, mock_embedding, memory_config):
    """Different sessions should have isolated session-level caches."""
    manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector, embedding=mock_embedding, dedup_llm=mock_llm)

    session1 = MemorySession(manager=manager, chat_id="chat1")
    session2 = MemorySession(manager=manager, chat_id="chat2")

    mem1 = session1.add_knowledge("Cache test content")
    mem2 = session2.add_knowledge("Cache test content")

    assert mem1 is not None
    assert mem2 is not None, "Different sessions should allow same content"
    assert session1.buffer_size == 1
    assert session2.buffer_size == 1


@pytest.mark.asyncio
async def test_normalization_consistency(mock_llm, mock_vector, mock_embedding, memory_config):
    """Session and global layers should use same normalization."""
    manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector, embedding=mock_embedding, dedup_llm=mock_llm)

    session1 = MemorySession(manager=manager, chat_id="chat1")
    session1.add_knowledge("café")
    stored1 = await session1.flush()
    assert len(stored1) == 1

    session2 = MemorySession(manager=manager, chat_id="chat2")
    session2.add_knowledge("CAFÉ")
    stored2 = await session2.flush()
    assert len(stored2) == 0, "Global layer should deduplicate Unicode variant"
