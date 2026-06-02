"""Performance benchmarks for memory toolkit critical paths.

Benchmarks establish quantitative performance baselines for:
- BM25 retrieval at different corpus sizes
- RRF fusion with multiple channels
- Batch storage operations
"""

from datetime import UTC, datetime

import pytest

from myrm_agent_harness.toolkits.memory._internal.storage import search_bm25
from myrm_agent_harness.toolkits.memory.config import MemoryConfig
from myrm_agent_harness.toolkits.memory.manager import MemoryManager
from myrm_agent_harness.toolkits.memory.protocols.vector import VectorDocument
from myrm_agent_harness.toolkits.memory.retriever import MemoryRetriever
from myrm_agent_harness.toolkits.memory.types import (
    EpisodicMemory,
    MemorySearchResult,
    MemoryType,
    SemanticMemory,
)


def create_vector_doc(
    doc_id: str, content: str, user_id: str = "bench_user"
) -> VectorDocument:
    """Factory for benchmark VectorDocument."""
    return VectorDocument(
        id=doc_id,
        content=content,
        vector=[0.1] * 768,
        metadata={
            "memory_type": "semantic",
            "importance": 0.5,
            "confidence": 1.0,
            "source_chat_id": "",
            "preference_type": "",
            "preference_strength": 0.0,
            "correction_of": "",
            "access_count": 0,
        },
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@pytest.fixture
def memory_config() -> MemoryConfig:
    """Create benchmark memory configuration with higher corpus size."""
    return MemoryConfig(
        embedding_model="test-model",
        collection_prefix="bench_memory",
        bm25_top_k=50,
        bm25_max_corpus_size=10000,
    )


class TestBM25RetrievalBenchmarks:
    """Benchmark BM25 retrieval at different corpus sizes."""

    @pytest.mark.asyncio
    @pytest.mark.benchmark(group="bm25", min_rounds=10)
    async def test_bm25_search_1000_corpus(self, benchmark, memory_config):
        """Benchmark BM25 search with 1000 documents.

        Performance threshold: < 200ms
        """
        from unittest.mock import AsyncMock

        mock_vector_store = AsyncMock()
        mock_vector_store.count.side_effect = [1000, 500]

        sem_docs = [
            create_vector_doc(f"sem-{i}", f"Python programming guide {i}")
            for i in range(700)
        ]
        epi_docs = [
            create_vector_doc(f"epi-{i}", f"Discussed API design {i}")
            for i in range(300)
        ]

        mock_vector_store.scroll.side_effect = [(sem_docs, None), (epi_docs, None)] * 10

        result = await benchmark.pedantic(
            search_bm25,
            args=("Python API", mock_vector_store, memory_config),
            rounds=10,
        )

        assert isinstance(result, list)

    @pytest.mark.asyncio
    @pytest.mark.benchmark(group="bm25", min_rounds=10)
    async def test_bm25_search_5000_corpus(self, benchmark, memory_config):
        """Benchmark BM25 search with 5000 documents (auto-degradation threshold).

        Performance threshold: < 500ms
        """
        from unittest.mock import AsyncMock

        mock_vector_store = AsyncMock()
        mock_vector_store.count.side_effect = [5000, 2500]

        sem_docs = [
            create_vector_doc(f"sem-{i}", f"Machine learning tutorial {i}")
            for i in range(3500)
        ]
        epi_docs = [
            create_vector_doc(f"epi-{i}", f"Discussed database design {i}")
            for i in range(1500)
        ]

        mock_vector_store.scroll.side_effect = [(sem_docs, None), (epi_docs, None)] * 10

        result = await benchmark.pedantic(
            search_bm25,
            args=("machine learning database", mock_vector_store, memory_config),
            rounds=10,
        )

        assert isinstance(result, list)

    @pytest.mark.asyncio
    @pytest.mark.benchmark(group="bm25", min_rounds=5)
    async def test_bm25_search_10000_corpus(self, benchmark, memory_config):
        """Benchmark BM25 search with 10000 documents (above threshold).

        Performance threshold: < 1000ms
        """
        from unittest.mock import AsyncMock

        mock_vector_store = AsyncMock()
        mock_vector_store.count.side_effect = [10000, 5000]

        sem_docs = [
            create_vector_doc(f"sem-{i}", f"Deep learning framework {i}")
            for i in range(7000)
        ]
        epi_docs = [
            create_vector_doc(f"epi-{i}", f"Discussed system architecture {i}")
            for i in range(3000)
        ]

        mock_vector_store.scroll.side_effect = [(sem_docs, None), (epi_docs, None)] * 5

        result = await benchmark.pedantic(
            search_bm25,
            args=("deep learning architecture", mock_vector_store, memory_config),
            rounds=5,
        )

        assert isinstance(result, list)


class TestRRFFusionBenchmarks:
    """Benchmark RRF fusion with different channel counts."""

    @pytest.mark.benchmark(group="rrf", min_rounds=50)
    def test_rrf_fusion_2_channels(self, benchmark, memory_config):
        """Benchmark RRF fusion with 2 result channels.

        Performance threshold: < 10ms
        """
        retriever = MemoryRetriever(memory_config.retrieval)

        channel1 = [
            MemorySearchResult(
                memory=SemanticMemory(content=f"Result {i}"),
                score=max(0.1, 0.9 - i * 0.04),
                memory_type=MemoryType.SEMANTIC,
            )
            for i in range(20)
        ]
        channel2 = [
            MemorySearchResult(
                memory=SemanticMemory(content=f"Result {i}"),
                score=max(0.1, 0.85 - i * 0.03),
                memory_type=MemoryType.SEMANTIC,
            )
            for i in range(20)
        ]

        result = benchmark(retriever.fuse, [channel1, channel2], limit=10)
        assert len(result) <= 10

    @pytest.mark.benchmark(group="rrf", min_rounds=50)
    def test_rrf_fusion_3_channels(self, benchmark, memory_config):
        """Benchmark RRF fusion with 3 result channels.

        Performance threshold: < 15ms
        """
        retriever = MemoryRetriever(memory_config.retrieval)

        channels = [
            [
                MemorySearchResult(
                    memory=SemanticMemory(content=f"Ch{ch}-{i}"),
                    score=max(0.1, 0.9 - i * 0.04),
                    memory_type=MemoryType.SEMANTIC,
                )
                for i in range(20)
            ]
            for ch in range(3)
        ]

        result = benchmark(retriever.fuse, channels, limit=10)
        assert len(result) <= 10

    @pytest.mark.benchmark(group="rrf", min_rounds=30)
    def test_rrf_fusion_5_channels(self, benchmark, memory_config):
        """Benchmark RRF fusion with 5 result channels (max typical).

        Performance threshold: < 20ms
        """
        retriever = MemoryRetriever(memory_config.retrieval)

        channels = [
            [
                MemorySearchResult(
                    memory=SemanticMemory(content=f"Ch{ch}-{i}"),
                    score=max(0.1, 0.9 - i * 0.04),
                    memory_type=MemoryType.SEMANTIC,
                )
                for i in range(20)
            ]
            for ch in range(5)
        ]

        result = benchmark(retriever.fuse, channels, limit=10)
        assert len(result) <= 10


class TestBatchStorageBenchmarks:
    """Benchmark batch storage operations."""

    @pytest.mark.asyncio
    @pytest.mark.benchmark(group="batch", min_rounds=10)
    async def test_batch_store_10_memories(
        self, benchmark, mock_vector_store, mock_embedding, memory_config
    ):
        """Benchmark batch store with 10 memories.

        Performance threshold: < 500ms
        """
        mock_embedding.embed_batch.return_value = [[0.1] * 768 for _ in range(10)]
        mock_vector_store.upsert.return_value = None

        manager = MemoryManager(
            memory_config,
            user_id="test_user",
            vector=mock_vector_store,
            embedding=mock_embedding,
        )

        memories = [
            SemanticMemory(content=f"Memory content {i}", importance=0.5)
            for i in range(10)
        ]

        result = await benchmark.pedantic(
            manager.store_batch, args=(memories,), rounds=10
        )

        assert len(result) == 10

    @pytest.mark.asyncio
    @pytest.mark.benchmark(group="batch", min_rounds=5)
    async def test_batch_store_50_memories(
        self, benchmark, mock_vector_store, mock_embedding, memory_config
    ):
        """Benchmark batch store with 50 memories.

        Performance threshold: < 1s
        """
        mock_embedding.embed_batch.return_value = [[0.1] * 768 for _ in range(50)]
        mock_vector_store.upsert.return_value = None

        manager = MemoryManager(
            memory_config,
            user_id="test_user",
            vector=mock_vector_store,
            embedding=mock_embedding,
        )

        memories = [
            SemanticMemory(content=f"Memory content {i}", importance=0.5)
            for i in range(50)
        ]

        result = await benchmark.pedantic(
            manager.store_batch, args=(memories,), rounds=5
        )

        assert len(result) == 50

    @pytest.mark.asyncio
    @pytest.mark.benchmark(group="batch", min_rounds=3)
    async def test_batch_store_100_memories(
        self, benchmark, mock_vector_store, mock_embedding, memory_config
    ):
        """Benchmark batch store with 100 memories.

        Performance threshold: < 2s
        """
        mock_embedding.embed_batch.return_value = [[0.1] * 768 for _ in range(100)]
        mock_vector_store.upsert.return_value = None

        manager = MemoryManager(
            memory_config,
            user_id="test_user",
            vector=mock_vector_store,
            embedding=mock_embedding,
        )

        memories = [
            EpisodicMemory(content=f"Conversation event {i}", importance=0.5)
            for i in range(100)
        ]

        result = await benchmark.pedantic(
            manager.store_batch, args=(memories,), rounds=3
        )

        assert len(result) == 100


class TestEndToEndBenchmarks:
    """Benchmark end-to-end workflows."""

    @pytest.mark.asyncio
    @pytest.mark.benchmark(group="e2e", min_rounds=10)
    async def test_search_with_bm25_and_vector(
        self, benchmark, mock_vector_store, mock_embedding, memory_config
    ):
        """Benchmark full search flow: embedding + vector + BM25 + RRF fusion.

        Performance threshold: < 800ms
        """
        from myrm_agent_harness.toolkits.memory.protocols.vector import (
            VectorSearchResult,
        )

        mock_embedding.embed.return_value = [0.1] * 768
        mock_vector_store.count.side_effect = lambda coll: 1000
        mock_vector_store.scroll.return_value = [
            create_vector_doc(f"doc-{i}", f"Python async programming {i}")
            for i in range(1000)
        ]

        doc = create_vector_doc("vec-1", "Python async best practices")
        mock_vector_store.search.return_value = [
            VectorSearchResult(document=doc, score=0.9)
        ]

        manager = MemoryManager(
            memory_config,
            user_id="test_user",
            vector=mock_vector_store,
            embedding=mock_embedding,
        )

        result = await benchmark.pedantic(
            manager.search,
            args=("Python async",),
            kwargs={
                "memory_types": [MemoryType.SEMANTIC, MemoryType.EPISODIC],
                "limit": 10,
                "use_rrf": True,
            },
            rounds=10,
        )

        assert isinstance(result, list)
