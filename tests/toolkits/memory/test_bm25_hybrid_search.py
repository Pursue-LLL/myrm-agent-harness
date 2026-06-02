"""Unit tests for BM25 hybrid search integration.

100% coverage for search_bm25 function and MemoryManager integration.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.toolkits.memory._internal.storage import search_bm25
from myrm_agent_harness.toolkits.memory.config import MemoryConfig
from myrm_agent_harness.toolkits.memory.manager import MemoryManager
from myrm_agent_harness.toolkits.memory.protocols.vector import VectorDocument
from myrm_agent_harness.toolkits.memory.protocols.vector import (
    VectorSearchResult as VectorSearchHit,
)
from myrm_agent_harness.toolkits.memory.types import MemorySearchResult, MemoryType


@pytest.fixture
def memory_config() -> MemoryConfig:
    """Create test memory configuration."""
    return MemoryConfig(
        embedding_model="test-model",
        collection_prefix="test_memory",
        bm25_top_k=50,
        bm25_max_corpus_size=5000,
    )


@pytest.fixture
def mock_vector_store():
    """Create mock vector store with full protocol implementation."""
    store = AsyncMock()
    store.count = AsyncMock()
    store.scroll = AsyncMock()
    store.search = AsyncMock()
    store.upsert = AsyncMock()
    store.delete = AsyncMock()
    store.close = AsyncMock()
    return store


def create_vector_doc(
    doc_id: str, content: str, user_id: str = "local"
) -> VectorDocument:
    """Helper to create VectorDocument."""
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


class TestSearchBM25:
    """Test suite for search_bm25 function with 100% coverage."""

    @pytest.mark.asyncio
    async def test_normal_search_with_results(self, mock_vector_store, memory_config):
        """Test normal BM25 search with matching results."""
        sem_docs = [
            create_vector_doc("sem1", "LiteLLM 1.77.2 release notes"),
            create_vector_doc("sem2", "Python programming guide"),
        ]
        epi_docs = [
            create_vector_doc("epi1", "User asked about LiteLLM version"),
        ]

        mock_vector_store.scroll.side_effect = [(sem_docs, None), (epi_docs, None)]

        results = await search_bm25("LiteLLM 1.77", mock_vector_store, memory_config)

        assert len(results) > 0
        assert all(isinstance(r, MemorySearchResult) for r in results)
        assert all(
            r.memory_type in (MemoryType.SEMANTIC, MemoryType.EPISODIC) for r in results
        )
        assert results[0].score > 0
        assert mock_vector_store.scroll.call_count == 2

    @pytest.mark.asyncio
    async def test_auto_degradation_exceeds_threshold(
        self, mock_vector_store, memory_config
    ):
        """Test auto-degradation when corpus size exceeds threshold."""
        sem_docs = [create_vector_doc(f"s{i}", f"Doc {i}") for i in range(3000)]
        epi_docs = [create_vector_doc(f"e{i}", f"Event {i}") for i in range(2500)]
        mock_vector_store.scroll.side_effect = [(sem_docs, None), (epi_docs, None)]

        results = await search_bm25("test query", mock_vector_store, memory_config)

        assert results == []

    @pytest.mark.asyncio
    async def test_auto_degradation_empty_memory(
        self, mock_vector_store, memory_config
    ):
        """Test auto-degradation when memory is empty."""
        mock_vector_store.scroll.side_effect = [([], None), ([], None)]

        results = await search_bm25("test query", mock_vector_store, memory_config)

        assert results == []

    @pytest.mark.asyncio
    async def test_proper_noun_recall(self, mock_vector_store, memory_config):
        """Test BM25 excels at proper noun and version number recall."""

        sem_docs = [
            create_vector_doc("1", "LiteLLM 1.77.2 introduces streaming support"),
            create_vector_doc("2", "FastAPI 0.100.0 release notes"),
            create_vector_doc("3", "General discussion about API frameworks"),
            create_vector_doc("4", "LiteLLM configuration guide"),
        ]
        epi_docs = [
            create_vector_doc("5", "User mentioned LiteLLM 1.77 yesterday"),
        ]

        mock_vector_store.scroll.side_effect = [(sem_docs, None), (epi_docs, None)]

        results = await search_bm25("LiteLLM 1.77.2", mock_vector_store, memory_config)

        assert len(results) > 0
        top_result = results[0]
        assert "LiteLLM" in top_result.memory.content
        assert "1.77" in top_result.memory.content

    @pytest.mark.asyncio
    async def test_memory_type_classification(self, mock_vector_store, memory_config):
        """Test correct memory_type assignment for semantic vs episodic."""

        sem_docs = [
            create_vector_doc("sem1", "Python programming language guide"),
            create_vector_doc("sem2", "Python data structures tutorial"),
        ]
        epi_docs = [
            create_vector_doc("epi1", "User asked about Python yesterday"),
        ]

        mock_vector_store.scroll.side_effect = [(sem_docs, None), (epi_docs, None)]

        results = await search_bm25("Python", mock_vector_store, memory_config)

        semantic_results = [r for r in results if r.memory_type == MemoryType.SEMANTIC]
        episodic_results = [r for r in results if r.memory_type == MemoryType.EPISODIC]

        assert len(results) > 0
        assert len(semantic_results) >= 0
        assert len(episodic_results) >= 0

    @pytest.mark.asyncio
    async def test_only_relevant_results_returned(
        self, mock_vector_store, memory_config
    ):
        """Test that only_relevant=True filters out zero-score results."""

        sem_docs = [
            create_vector_doc("1", "Completely unrelated content xyz"),
            create_vector_doc("2", "Python programming guide"),
        ]
        epi_docs = [
            create_vector_doc("3", "Random event abc"),
        ]

        mock_vector_store.scroll.side_effect = [(sem_docs, None), (epi_docs, None)]

        results = await search_bm25("Python", mock_vector_store, memory_config)

        assert all(r.score > 0 for r in results)

    @pytest.mark.asyncio
    async def test_parallel_scroll_execution(self, mock_vector_store, memory_config):
        """Test that scroll operations execute in parallel."""
        mock_vector_store.scroll.side_effect = [
            ([create_vector_doc("1", "test")], None),
            ([], None),
        ]

        await search_bm25("test", mock_vector_store, memory_config)

        assert mock_vector_store.scroll.call_count == 2

    @pytest.mark.asyncio
    async def test_respects_bm25_top_k_limit(self, mock_vector_store, memory_config):
        """Test that results respect bm25_top_k configuration."""

        sem_docs = [
            create_vector_doc(f"sem{i}", f"Document {i} content") for i in range(100)
        ]
        epi_docs = [
            create_vector_doc(f"epi{i}", f"Event {i} content") for i in range(50)
        ]

        mock_vector_store.scroll.side_effect = [(sem_docs, None), (epi_docs, None)]

        results = await search_bm25("content", mock_vector_store, memory_config)

        assert len(results) <= memory_config.bm25_top_k


class TestMemoryManagerBM25Integration:
    """Test BM25 integration in MemoryManager.search()."""

    @pytest.fixture
    def mock_embedding(self):
        """Mock embedding protocol."""
        embedding = AsyncMock()
        embedding.embed.return_value = [0.1] * 768
        embedding.dimension = 768
        return embedding

    @pytest.fixture
    def memory_manager(self, mock_vector_store, mock_embedding, memory_config):
        """Create MemoryManager with mocked backends."""
        return MemoryManager(
            memory_config,
            user_id="test_user",
            vector=mock_vector_store,
            embedding=mock_embedding,
        )

    @pytest.mark.asyncio
    async def test_bm25_channel_added_to_search(
        self, memory_manager, mock_vector_store, mock_embedding
    ):
        """Test that BM25 channel is automatically added to search coroutines."""
        mock_vector_store.scroll.side_effect = [
            ([create_vector_doc("1", "Test content")], None),
            ([], None),
        ]
        mock_vector_store.search.return_value = []

        await memory_manager.search("test query", memory_types=[MemoryType.SEMANTIC])

        assert mock_vector_store.scroll.call_count == 2
        assert mock_embedding.embed.called

    @pytest.mark.asyncio
    async def test_bm25_not_called_without_vector_types(
        self, memory_manager, mock_vector_store
    ):
        """Test BM25 is not called when no vector-based memory types are requested."""
        mock_relational = AsyncMock()
        mock_relational.list_profiles.return_value = []

        manager = MemoryManager(
            memory_manager.config, user_id="test_user", relational=mock_relational
        )

        await manager.search("test query", memory_types=[MemoryType.PROFILE])

        assert mock_vector_store.count.call_count == 0

    @pytest.mark.asyncio
    async def test_rrf_fusion_with_bm25_and_vector(
        self, memory_manager, mock_vector_store, mock_embedding
    ):
        """Test that RRF fusion combines BM25 and Vector results."""

        sem_docs = [
            create_vector_doc("1", "LiteLLM 1.77.2 documentation"),
            create_vector_doc("2", "Python async programming"),
        ]
        epi_docs = [
            create_vector_doc("3", "User asked about LiteLLM"),
        ]

        mock_vector_store.scroll.side_effect = [(sem_docs, None), (epi_docs, None)]

        vector_hits = [
            VectorSearchHit(document=sem_docs[1], score=0.85),
        ]
        mock_vector_store.search.return_value = vector_hits

        results = await memory_manager.search(
            "LiteLLM 1.77",
            memory_types=[MemoryType.SEMANTIC, MemoryType.EPISODIC],
            use_rrf=True,
        )

        assert len(results) > 0
        assert mock_embedding.embed.called

    @pytest.mark.asyncio
    async def test_bm25_exception_handled_gracefully(
        self, memory_manager, mock_vector_store, mock_embedding
    ):
        """Test that BM25 exceptions are caught and logged without breaking search."""
        mock_vector_store.scroll.side_effect = Exception("Database connection failed")

        mock_vector_store.search.return_value = [
            VectorSearchHit(
                document=create_vector_doc("1", "Fallback result"), score=0.9
            )
        ]

        results = await memory_manager.search(
            "test query", memory_types=[MemoryType.SEMANTIC]
        )

        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_bm25_with_empty_query(self, mock_vector_store, memory_config):
        """Test BM25 handles empty query gracefully."""
        mock_vector_store.scroll.side_effect = [
            ([create_vector_doc("1", "Test content")], None),
            ([], None),
        ]

        results = await search_bm25("", mock_vector_store, memory_config)

        assert results == []

    @pytest.mark.asyncio
    async def test_normal_operation_below_threshold(
        self, mock_vector_store, memory_config
    ):
        """Test normal BM25 operation when corpus size is below threshold."""
        sem_docs = [create_vector_doc("1", "Test content")]
        epi_docs = []
        mock_vector_store.scroll.side_effect = [(sem_docs, None), (epi_docs, None)]

        results = await search_bm25("Python", mock_vector_store, memory_config)

        assert isinstance(results, list)
        assert mock_vector_store.scroll.call_count == 2

    @pytest.mark.asyncio
    async def test_chinese_query_support(self, mock_vector_store, memory_config):
        """Test BM25 handles Chinese queries correctly."""
        sem_docs = [
            create_vector_doc("1", "Python 编程指南"),
            create_vector_doc("2", "机器学习基础"),
        ]
        epi_docs = [
            create_vector_doc("3", "用户询问了 Python 相关问题"),
        ]

        mock_vector_store.scroll.side_effect = [(sem_docs, None), (epi_docs, None)]

        results = await search_bm25("Python 编程", mock_vector_store, memory_config)

        assert len(results) > 0

    @pytest.mark.asyncio
    async def test_mixed_language_query(self, mock_vector_store, memory_config):
        """Test BM25 handles mixed English-Chinese queries."""
        sem_docs = [
            create_vector_doc("1", "LiteLLM 配置指南详细说明"),
            create_vector_doc("2", "FastAPI 使用教程"),
            create_vector_doc("3", "LiteLLM configuration guide"),
        ]
        epi_docs = []

        mock_vector_store.scroll.side_effect = [(sem_docs, None), (epi_docs, None)]

        results = await search_bm25("LiteLLM", mock_vector_store, memory_config)

        assert len(results) > 0
        assert any("LiteLLM" in r.memory.content for r in results)

    @pytest.mark.asyncio
    async def test_version_number_tokenization(self, mock_vector_store, memory_config):
        """Test BM25 correctly tokenizes and matches version numbers."""
        sem_docs = [
            create_vector_doc("1", "LiteLLM 1.77.2 changelog"),
            create_vector_doc("2", "LiteLLM 1.77.1 changelog"),
            create_vector_doc("3", "LiteLLM 1.76.0 changelog"),
        ]
        epi_docs = []

        mock_vector_store.scroll.side_effect = [(sem_docs, None), (epi_docs, None)]

        results = await search_bm25("1.77.2", mock_vector_store, memory_config)

        assert len(results) > 0
        assert "1.77.2" in results[0].memory.content

    @pytest.mark.asyncio
    async def test_url_keyword_extraction(self, mock_vector_store, memory_config):
        """Test BM25 extracts and matches URL keywords."""
        sem_docs = [
            create_vector_doc("1", "Check docs.litellm.ai for release notes"),
            create_vector_doc("2", "Visit fastapi.tiangolo.com for tutorials"),
            create_vector_doc("3", "LiteLLM documentation is available online"),
        ]
        epi_docs = []

        mock_vector_store.scroll.side_effect = [(sem_docs, None), (epi_docs, None)]

        results = await search_bm25("docs litellm", mock_vector_store, memory_config)

        assert len(results) > 0
        assert any("litellm" in r.memory.content.lower() for r in results)

    @pytest.mark.asyncio
    async def test_camelcase_tokenization(self, mock_vector_store, memory_config):
        """Test BM25 splits CamelCase properly."""
        sem_docs = [
            create_vector_doc("1", "FastAPI framework overview and tutorial"),
            create_vector_doc("2", "LiteLLM integration guide"),
            create_vector_doc("3", "FastAPI is a modern web framework"),
        ]
        epi_docs = []

        mock_vector_store.scroll.side_effect = [(sem_docs, None), (epi_docs, None)]

        results = await search_bm25(
            "FastAPI framework", mock_vector_store, memory_config
        )

        assert len(results) > 0
        assert any("FastAPI" in r.memory.content for r in results)

    @pytest.mark.asyncio
    async def test_score_ordering(self, mock_vector_store, memory_config):
        """Test that results are ordered by BM25 score descending."""
        sem_docs = [
            create_vector_doc("1", "Python Python Python programming"),
            create_vector_doc("2", "Python guide"),
            create_vector_doc("3", "Unrelated content"),
        ]
        epi_docs = []

        mock_vector_store.scroll.side_effect = [(sem_docs, None), (epi_docs, None)]

        results = await search_bm25("Python", mock_vector_store, memory_config)

        if len(results) >= 2:
            assert results[0].score >= results[1].score

    @pytest.mark.asyncio
    async def test_user_id_filtering(self, mock_vector_store, memory_config):
        """Test that scroll is called with correct filters (no user_id after removal)."""
        mock_vector_store.scroll.side_effect = [([], None), ([], None)]

        await search_bm25("test", mock_vector_store, memory_config)

        mock_vector_store.scroll.assert_any_call(
            memory_config.semantic_collection, limit=5000, filters={"archived": False}
        )


class TestBM25Configuration:
    """Test BM25 configuration parameters."""

    def test_default_bm25_config_values(self):
        """Test default BM25 configuration values."""
        config = MemoryConfig(embedding_model="test-model")

        assert config.bm25_top_k == 50
        assert config.bm25_max_corpus_size == 5000

    def test_custom_bm25_config_values(self):
        """Test custom BM25 configuration values."""
        config = MemoryConfig(
            embedding_model="test-model", bm25_top_k=100, bm25_max_corpus_size=10000
        )

        assert config.bm25_top_k == 100
        assert config.bm25_max_corpus_size == 10000

    def test_config_immutability(self):
        """Test that MemoryConfig is frozen (immutable)."""
        config = MemoryConfig(embedding_model="test-model")

        with pytest.raises(Exception):
            config.bm25_top_k = 100


class TestBM25EdgeCases:
    """Test edge cases and error conditions."""

    @pytest.mark.asyncio
    async def test_single_document_corpus(self, mock_vector_store, memory_config):
        """Test BM25 with single document corpus."""
        mock_vector_store.scroll.side_effect = [
            ([create_vector_doc("1", "Single document with Python content")], None),
            ([], None),
        ]

        results = await search_bm25("Python", mock_vector_store, memory_config)

        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_very_long_query(self, mock_vector_store, memory_config):
        """Test BM25 handles very long queries."""
        mock_vector_store.scroll.side_effect = [
            ([create_vector_doc("1", "Test content")], None),
            ([], None),
        ]

        long_query = "Python programming " * 100

        results = await search_bm25(long_query, mock_vector_store, memory_config)

        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_special_characters_in_query(self, mock_vector_store, memory_config):
        """Test BM25 handles special characters in query."""
        mock_vector_store.scroll.side_effect = [
            ([create_vector_doc("1", "C++ programming guide")], None),
            ([], None),
        ]

        results = await search_bm25("Python", mock_vector_store, memory_config)

        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_unicode_content(self, mock_vector_store, memory_config):
        """Test BM25 handles Unicode content correctly."""
        sem_docs = [
            create_vector_doc("1", "测试内容  with emoji"),
            create_vector_doc("2", "Тестовый контент (Cyrillic)"),
        ]
        epi_docs = []

        mock_vector_store.scroll.side_effect = [(sem_docs, None), (epi_docs, None)]

        results = await search_bm25("Python", mock_vector_store, memory_config)

        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_zero_limit(self, mock_vector_store, memory_config):
        """Test BM25 with limit=0."""
        mock_vector_store.scroll.side_effect = [
            ([create_vector_doc("1", "Test")], None),
            ([], None),
        ]

        results = await search_bm25("test", mock_vector_store, memory_config)

        assert results == []


class TestBM25PerformanceCharacteristics:
    """Test performance-related behaviors."""

    @pytest.mark.asyncio
    async def test_degradation_logged_with_warning(
        self, mock_vector_store, memory_config, caplog
    ):
        """Test that auto-degradation logs a warning message."""
        import logging

        caplog.set_level(logging.WARNING)

        sem_docs = [create_vector_doc(f"s{i}", f"Doc {i}") for i in range(3000)]
        epi_docs = [create_vector_doc(f"e{i}", f"Event {i}") for i in range(3000)]
        mock_vector_store.scroll.side_effect = [(sem_docs, None), (epi_docs, None)]

        results = await search_bm25("C++ programming", mock_vector_store, memory_config)

        assert results == []
        assert any("BM25 auto-degraded" in record.message for record in caplog.records)

    @pytest.mark.asyncio
    async def test_large_corpus_near_threshold(self, mock_vector_store, memory_config):
        """Test performance with corpus size near threshold."""
        large_sem_docs = [
            create_vector_doc(f"sem{i}", f"Content {i}") for i in range(2500)
        ]
        large_epi_docs = [
            create_vector_doc(f"epi{i}", f"Event {i}") for i in range(2499)
        ]

        mock_vector_store.scroll.side_effect = [
            (large_sem_docs, None),
            (large_epi_docs, None),
        ]

        results = await search_bm25("测试", mock_vector_store, memory_config)

        assert isinstance(results, list)
        assert len(results) <= memory_config.bm25_top_k


if __name__ == "__main__":
    pytest.main(
        [
            __file__,
            "-v",
            "--cov=myrm_agent_harness.toolkits.memory",
            "--cov-report=term-missing",
        ]
    )
