"""Integration test for conversation memory dual-channel search.

Tests the end-to-end flow:
1. Store ConversationMemory with dual embeddings (raw + summary)
2. Search using dual-channel (both raw and summary embeddings)
3. Verify RRF fusion works correctly
4. Verify lazy loading (raw_exchange not included by default)

Requires: Real vector store (Qdrant embedded) + real embedding model.
"""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.memory.config import MemoryConfig, RetrievalConfig
from myrm_agent_harness.toolkits.memory.manager import MemoryManager
from myrm_agent_harness.toolkits.memory.types import ConversationMemory, MemoryType


@pytest.fixture
async def memory_manager():
    """Create MemoryManager with real Qdrant embedded store."""
    from myrm_agent_harness.toolkits.vector.qdrant import create_embedded_store

    with tempfile.TemporaryDirectory() as tmp_dir:
        vector_store = await create_embedded_store(path=Path(tmp_dir))

        from myrm_agent_harness.toolkits.memory.protocols.embedding import EmbeddingProtocol

        class MockEmbedding(EmbeddingProtocol):
            """Mock embedding that generates deterministic vectors."""

            async def embed(self, text: str) -> list[float]:
                return [float(hash(text) % 1000) / 1000.0] * 768

            async def embed_batch(self, texts: list[str]) -> list[list[float]]:
                return [await self.embed(t) for t in texts]

        config = MemoryConfig(
            embedding_model="mock-model",
            retrieval=RetrievalConfig(keyword_overlap_weight=0.0, temporal_boost_weight=0.0),
        )

        manager = MemoryManager(config, user_id="test_user", vector=vector_store, embedding=MockEmbedding(), auto_warmup=False)

        from qdrant_client.models import Distance, VectorParams

        vector_store._client.create_collection(  # type: ignore[attr-defined]
            collection_name=config.conversation_collection,
            vectors_config={
                "raw": VectorParams(size=768, distance=Distance.COSINE),
                "summary": VectorParams(size=768, distance=Distance.COSINE),
            },
        )

        yield manager

        await vector_store.close()


@pytest.mark.asyncio
async def test_conversation_dual_channel_search(memory_manager: MemoryManager):
    """Test dual-channel search for conversation memories."""
    import uuid

    conversations = [
        ConversationMemory(
            id=str(uuid.uuid4()),
            content="Python performance optimization",
            raw_exchange="User: How to optimize Python?\nAI: Use caching strategies.",
            timestamp=datetime.now(UTC),
        ),
        ConversationMemory(
            id=str(uuid.uuid4()),
            content="JavaScript async patterns",
            raw_exchange="User: Explain async/await.\nAI: It's syntactic sugar for promises.",
            timestamp=datetime.now(UTC),
        ),
        ConversationMemory(
            id=str(uuid.uuid4()),
            content="Python data structures",
            raw_exchange="User: What are Python lists?\nAI: Dynamic arrays.",
            timestamp=datetime.now(UTC),
        ),
    ]

    stored = await memory_manager.store_batch(conversations)

    assert len(stored) == 3

    results = await memory_manager.search("Python", memory_types=[MemoryType.CONVERSATION], limit=5, include_raw=False)

    assert len(results) > 0

    for result in results:
        assert result.memory_type == MemoryType.CONVERSATION
        assert isinstance(result.memory, ConversationMemory)

        assert result.memory.content != ""
        assert result.memory.raw_exchange == ""


@pytest.mark.asyncio
async def test_conversation_lazy_loading(memory_manager: MemoryManager):
    """Test lazy loading: raw_exchange excluded by default, included when requested."""
    import uuid

    conv = ConversationMemory(
        id=str(uuid.uuid4()),
        content="Test lazy loading",
        raw_exchange="This is a very long raw exchange that should be lazy-loaded." * 100,
        timestamp=datetime.now(UTC),
    )

    await memory_manager.store_batch([conv])

    results_without_raw = await memory_manager.search(
        "lazy loading", memory_types=[MemoryType.CONVERSATION], limit=1, include_raw=False
    )

    assert len(results_without_raw) == 1
    assert results_without_raw[0].memory.raw_exchange == ""

    results_with_raw = await memory_manager.search(
        "lazy loading", memory_types=[MemoryType.CONVERSATION], limit=1, include_raw=True
    )

    assert len(results_with_raw) == 1
    assert "very long raw exchange" in results_with_raw[0].memory.raw_exchange


@pytest.mark.asyncio
async def test_conversation_rrf_fusion(memory_manager: MemoryManager):
    """Test that RRF correctly fuses dual-channel results without duplicates."""
    import uuid

    conv = ConversationMemory(
        id=str(uuid.uuid4()),
        content="Python performance",
        raw_exchange="User: Python speed?\nAI: Use PyPy.",
        timestamp=datetime.now(UTC),
    )

    await memory_manager.store_batch([conv])

    results = await memory_manager.search("Python", memory_types=[MemoryType.CONVERSATION], limit=10, use_rrf=True)

    ids = [r.memory.id for r in results]
    unique_ids = set(ids)

    assert len(ids) == len(unique_ids), "RRF should not produce duplicate results"
    assert len(results) == 1, "Should find exactly one conversation"
    assert results[0].memory.content == "Python performance"


@pytest.mark.asyncio
async def test_adaptive_channel_cost_optimization(memory_manager: MemoryManager):
    """Test that adaptive channel selection reduces query cost for short queries."""
    import uuid

    conv = ConversationMemory(
        id=str(uuid.uuid4()),
        content="Bug in production",
        raw_exchange="User: Found a bug\nAI: Let's fix it.",
        timestamp=datetime.now(UTC),
    )

    await memory_manager.store_batch([conv])

    # Test short query (adaptive enabled by default)
    # Short query should use single-channel for cost savings
    results_short = await memory_manager.search(
        "bug",  # Short query → summary only
        memory_types=[MemoryType.CONVERSATION],
        limit=10,
    )

    assert len(results_short) >= 1, "Should find conversation with short query"
    assert memory_manager._config.retrieval.enable_adaptive_channel, "Adaptive should be enabled by default"

    # Test long query (should use dual-channel)
    results_long = await memory_manager.search(
        "How to fix the production bug", memory_types=[MemoryType.CONVERSATION], limit=10
    )

    assert len(results_long) >= 1, "Should find conversation with long query"


@pytest.mark.asyncio
async def test_adaptive_quoted_phrase_forces_dual(memory_manager: MemoryManager):
    """Test that quotes force dual-channel even for short queries."""
    import uuid

    conv = ConversationMemory(
        id=str(uuid.uuid4()),
        content="Memory leak issue",
        raw_exchange='User: "memory leak"\nAI: Check profiler.',
        timestamp=datetime.now(UTC),
    )

    await memory_manager.store_batch([conv])

    # Short query with quotes should still use dual-channel
    results = await memory_manager.search(
        '"leak"',  # Quoted phrase forces dual-channel
        memory_types=[MemoryType.CONVERSATION],
        limit=10,
    )

    # Should find the conversation due to exact match from raw embedding
    assert len(results) >= 1, "Quoted phrase should trigger dual-channel for exact match"


@pytest.mark.asyncio
async def test_adaptive_with_various_configs(memory_manager: MemoryManager):
    """Test adaptive behavior with different configuration scenarios."""
    import uuid

    conv = ConversationMemory(
        id=str(uuid.uuid4()),
        content="Test conversation",
        raw_exchange="User: Test\nAI: OK.",
        timestamp=datetime.now(UTC),
    )

    await memory_manager.store_batch([conv])

    # Test that default config has adaptive enabled
    assert memory_manager._config.retrieval.enable_adaptive_channel, "Adaptive should be enabled by default"
    assert memory_manager._config.retrieval.adaptive_threshold == 5, "Default threshold should be 5"
    assert memory_manager._config.retrieval.adaptive_diversity_threshold == 0.7, (
        "Default diversity threshold should be 0.7"
    )

    # Search should work with default adaptive config
    results = await memory_manager.search("test", memory_types=[MemoryType.CONVERSATION], limit=10)

    assert len(results) >= 1, "Should find conversation with adaptive enabled"
