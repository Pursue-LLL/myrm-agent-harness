"""Tests for storage.py internal helper functions.

Covers critical paths:
- Embedding cache miss scenarios
- Graph indexing storage
- Error handling utilities
"""

from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.toolkits.memory._internal.storage import (
    _get_adaptive_threshold,
    _safe_float,
    _safe_int,
    doc_to_semantic,
    embed_batch,
    embed_single,
    semantic_to_doc,
    store_episodic,
    store_episodics_batch,
)
from myrm_agent_harness.toolkits.memory.protocols.graph import GraphNode
from myrm_agent_harness.toolkits.memory.types import EpisodicMemory, SemanticMemory


class TestEmbeddingCacheMiss:
    """Test embed_batch cache miss scenarios."""

    @pytest.mark.asyncio
    async def test_cache_complete_hit(self, mock_embedding, mock_cache):
        """Test cache returns all embeddings (no miss)."""
        texts = ["text1", "text2", "text3"]
        cached_vecs = [[0.1] * 768, [0.2] * 768, [0.3] * 768]
        mock_cache.get_batch.return_value = cached_vecs

        result = await embed_batch(texts, mock_embedding, mock_cache)

        assert result == cached_vecs
        mock_cache.get_batch.assert_awaited_once_with(texts)
        mock_embedding.embed_batch.assert_not_awaited()
        mock_cache.put_batch.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cache_partial_miss(self, mock_embedding, mock_cache):
        """Test cache partial miss triggers embedding for missing items."""
        texts = ["text1", "text2", "text3"]
        mock_cache.get_batch.return_value = [[0.1] * 768, None, [0.3] * 768]
        mock_embedding.embed_batch.return_value = [[0.2] * 768]

        result = await embed_batch(texts, mock_embedding, mock_cache)

        assert len(result) == 3
        assert result[0] == [0.1] * 768
        assert result[1] == [0.2] * 768
        assert result[2] == [0.3] * 768
        mock_embedding.embed_batch.assert_awaited_once_with(["text2"])
        mock_cache.put_batch.assert_awaited_once_with(["text2"], [[0.2] * 768])

    @pytest.mark.asyncio
    async def test_cache_complete_miss(self, mock_embedding, mock_cache):
        """Test cache complete miss triggers embedding for all items."""
        texts = ["text1", "text2"]
        mock_cache.get_batch.return_value = [None, None]
        mock_embedding.embed_batch.return_value = [[0.1] * 768, [0.2] * 768]

        result = await embed_batch(texts, mock_embedding, mock_cache)

        assert result == [[0.1] * 768, [0.2] * 768]
        mock_embedding.embed_batch.assert_awaited_once_with(texts)
        mock_cache.put_batch.assert_awaited_once_with(texts, [[0.1] * 768, [0.2] * 768])

    @pytest.mark.asyncio
    async def test_cache_none_bypasses_cache(self, mock_embedding):
        """Test cache=None directly calls embedding without caching."""
        texts = ["text1", "text2"]
        mock_embedding.embed_batch.return_value = [[0.1] * 768, [0.2] * 768]

        result = await embed_batch(texts, mock_embedding, cache=None)

        assert result == [[0.1] * 768, [0.2] * 768]
        mock_embedding.embed_batch.assert_awaited_once_with(texts)

    @pytest.mark.asyncio
    async def test_empty_texts_returns_empty(self, mock_embedding, mock_cache):
        """Test empty input returns empty list without cache/embedding calls."""
        result = await embed_batch([], mock_embedding, mock_cache)

        assert result == []
        mock_cache.get_batch.assert_not_awaited()
        mock_embedding.embed_batch.assert_not_awaited()


class TestAdaptiveThresholdCache:
    """Test adaptive threshold uses safe integer counts."""

    @pytest.mark.asyncio
    async def test_get_adaptive_threshold_ignores_non_numeric_count(self, mock_vector_store, memory_config):
        mock_vector_store.count = AsyncMock(return_value=object())

        threshold = await _get_adaptive_threshold(mock_vector_store, [memory_config.semantic_collection], memory_config)

        assert isinstance(threshold, float)
        assert threshold == memory_config.adaptive_threshold_strategy.get_threshold(0)


class TestGraphIndexingStorage:
    """Test episodic memory graph indexing storage."""

    @pytest.mark.asyncio
    async def test_store_episodic_with_graph_indexing(
        self, mock_vector_store, mock_embedding, mock_cache, mock_graph_store, memory_config
    ):
        """Test episodic storage creates graph nodes and relationships."""
        memory = EpisodicMemory(
            id="mem-1",
            content="Meeting with Alice and Bob",
            related_entities=["Alice", "Bob"],
            embedding=[0.1] * 768,
        )

        result = await store_episodic(
            memory=memory,
            vector=mock_vector_store,
            config=memory_config,
            embedding=mock_embedding,
            cache=mock_cache,
            graph=mock_graph_store,
        )

        assert result == memory
        mock_vector_store.upsert.assert_awaited_once()
        mock_graph_store.create_node.assert_awaited_once_with(
            labels=["EpisodicMemory"], properties={"id": "mem-1"}
        )
        assert mock_graph_store.get_or_create_node.await_count == 2
        assert mock_graph_store.create_relationship.await_count == 2

    @pytest.mark.asyncio
    async def test_store_episodic_without_graph(self, mock_vector_store, mock_embedding, mock_cache, memory_config):
        """Test episodic storage without graph backend skips graph indexing."""
        memory = EpisodicMemory(
            id="mem-1",
            content="Meeting with Alice",
            related_entities=["Alice"],
            embedding=[0.1] * 768,
        )

        result = await store_episodic(
            memory=memory,
            vector=mock_vector_store,
            config=memory_config,
            embedding=mock_embedding,
            cache=mock_cache,
            graph=None,
        )

        assert result == memory
        mock_vector_store.upsert.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_store_episodic_graph_failure_non_fatal(
        self, mock_vector_store, mock_embedding, mock_cache, mock_graph_store, memory_config
    ):
        """Test graph indexing failure does not prevent memory storage."""
        memory = EpisodicMemory(
            id="mem-1",
            content="Meeting with Alice",
            related_entities=["Alice"],
            embedding=[0.1] * 768,
        )
        mock_graph_store.create_node.side_effect = RuntimeError("Graph unavailable")

        result = await store_episodic(
            memory=memory,
            vector=mock_vector_store,
            config=memory_config,
            embedding=mock_embedding,
            cache=mock_cache,
            graph=mock_graph_store,
        )

        assert result == memory
        mock_vector_store.upsert.assert_awaited_once()
        mock_graph_store.create_node.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_store_episodics_batch_with_graph(
        self, mock_vector_store, mock_embedding, mock_cache, mock_graph_store, memory_config
    ):
        """Test batch episodic storage with graph indexing."""
        memories = [
            EpisodicMemory(
                id=f"mem-{i}",
                content=f"Event {i}",
                related_entities=["Alice"],
                embedding=[0.1 * i] * 768,
            )
            for i in range(1, 4)
        ]

        result = await store_episodics_batch(
            memories=memories,
            vector=mock_vector_store,
            config=memory_config,
            embedding=mock_embedding,
            cache=mock_cache,
            graph=mock_graph_store,
        )

        assert result == memories
        mock_vector_store.upsert.assert_awaited_once()
        assert mock_graph_store.create_node.await_count == 3
        assert mock_graph_store.get_or_create_node.await_count == 3
        assert mock_graph_store.create_relationship.await_count == 3

    @pytest.mark.asyncio
    async def test_store_episodics_batch_graph_failure_partial(
        self, mock_vector_store, mock_embedding, mock_cache, mock_graph_store, memory_config
    ):
        """Test batch graph indexing failure for one item does not affect others."""
        memories = [
            EpisodicMemory(
                id="mem-1", content="Event 1", related_entities=["Alice"], embedding=[0.1] * 768
            ),
            EpisodicMemory(
                id="mem-2", content="Event 2", related_entities=["Bob"], embedding=[0.2] * 768
            ),
        ]

        call_count = 0

        async def create_node_with_failure(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Graph error")
            return GraphNode(id=f"node-{call_count}", labels=["EpisodicMemory"], properties={})

        mock_graph_store.create_node.side_effect = create_node_with_failure

        result = await store_episodics_batch(
            memories=memories,
            vector=mock_vector_store,
            config=memory_config,
            embedding=mock_embedding,
            cache=mock_cache,
            graph=mock_graph_store,
        )

        assert result == memories
        mock_vector_store.upsert.assert_awaited_once()
        assert mock_graph_store.create_node.await_count == 2


class TestSemanticSourceErrorRoundTrip:
    """Test source_error field survives serialization/deserialization."""

    def test_source_error_round_trip_with_value(self):
        mem = SemanticMemory(content="Prefers tabs", source_error="Agent used spaces")
        doc = semantic_to_doc(mem)
        assert doc.metadata["source_error"] == "Agent used spaces"

        restored = doc_to_semantic(doc)
        assert restored.source_error == "Agent used spaces"
        assert restored.content == "Prefers tabs"

    def test_source_error_round_trip_none(self):
        mem = SemanticMemory(content="Normal fact")
        assert mem.source_error is None

        doc = semantic_to_doc(mem)
        assert doc.metadata["source_error"] == ""

        restored = doc_to_semantic(doc)
        assert restored.source_error is None

    def test_source_error_not_leaked_to_extra_metadata(self):
        mem = SemanticMemory(content="Correction memory", source_error="Used wrong API")
        doc = semantic_to_doc(mem)
        restored = doc_to_semantic(doc)
        assert "source_error" not in restored.metadata


class TestErrorHandlingUtilities:
    """Test _safe_float and _safe_int error handling."""

    def test_safe_float_valid_conversions(self):
        """Test _safe_float converts valid inputs correctly."""
        assert _safe_float(3.14) == 3.14
        assert _safe_float("2.5") == 2.5
        assert _safe_float(42) == 42.0
        assert _safe_float("0") == 0.0

    def test_safe_float_invalid_returns_default(self):
        """Test _safe_float returns default for invalid inputs."""
        assert _safe_float(None) == 0.0
        assert _safe_float("invalid") == 0.0
        assert _safe_float([1, 2, 3]) == 0.0
        assert _safe_float({}) == 0.0
        assert _safe_float(None, default=1.5) == 1.5

    def test_safe_int_valid_conversions(self):
        """Test _safe_int converts valid inputs correctly."""
        assert _safe_int(42) == 42
        assert _safe_int("100") == 100
        assert _safe_int(3.14) == 3
        assert _safe_int("0") == 0

    def test_safe_int_invalid_returns_default(self):
        """Test _safe_int returns default for invalid inputs."""
        assert _safe_int(None) == 0
        assert _safe_int("invalid") == 0
        assert _safe_int([1, 2]) == 0
        assert _safe_int({}) == 0
        assert _safe_int(None, default=999) == 999


class TestEmbedSingleCacheMiss:
    """Test embed_single cache miss scenarios."""

    @pytest.mark.asyncio
    async def test_embed_single_with_cache_hit(self, mock_embedding, mock_cache):
        """Test embed_single returns cached embedding."""
        mock_cache.get.return_value = [0.5] * 768

        result = await embed_single("test text", mock_embedding, mock_cache)

        assert result == [0.5] * 768
        mock_cache.get.assert_awaited_once_with("test text")
        mock_embedding.embed.assert_not_awaited()
        mock_cache.put.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_embed_single_with_cache_miss(self, mock_embedding, mock_cache):
        """Test embed_single on cache miss generates and caches embedding."""
        mock_cache.get.return_value = None
        mock_embedding.embed.return_value = [0.7] * 768

        result = await embed_single("test text", mock_embedding, mock_cache)

        assert result == [0.7] * 768
        mock_cache.get.assert_awaited_once_with("test text")
        mock_embedding.embed.assert_awaited_once_with("test text")
        mock_cache.put.assert_awaited_once_with("test text", [0.7] * 768)

    @pytest.mark.asyncio
    async def test_embed_single_without_cache(self, mock_embedding):
        """Test embed_single without cache directly calls embedding."""
        mock_embedding.embed.return_value = [0.9] * 768

        result = await embed_single("test text", mock_embedding, cache=None)

        assert result == [0.9] * 768
        mock_embedding.embed.assert_awaited_once_with("test text")


class TestExpectedValidDaysRoundTrip:
    """Test expected_valid_days survives serialize → deserialize cycle."""

    def test_evd_with_value(self):
        mem = SemanticMemory(content="User lives in Tokyo", expected_valid_days=365)
        doc = semantic_to_doc(mem)
        assert doc.metadata["expected_valid_days"] == 365

        restored = doc_to_semantic(doc)
        assert restored.expected_valid_days == 365

    def test_evd_none_serializes_as_zero(self):
        mem = SemanticMemory(content="Generic fact", expected_valid_days=None)
        doc = semantic_to_doc(mem)
        assert doc.metadata["expected_valid_days"] == 0

        restored = doc_to_semantic(doc)
        assert restored.expected_valid_days is None

    def test_evd_zero_treated_as_none(self):
        mem = SemanticMemory(content="Test", expected_valid_days=0)
        doc = semantic_to_doc(mem)
        restored = doc_to_semantic(doc)
        assert restored.expected_valid_days is None

    def test_evd_not_in_extra_metadata(self):
        mem = SemanticMemory(content="Test", expected_valid_days=90)
        doc = semantic_to_doc(mem)
        restored = doc_to_semantic(doc)
        assert "expected_valid_days" not in restored.metadata
