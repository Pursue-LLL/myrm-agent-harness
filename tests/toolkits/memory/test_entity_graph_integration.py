"""Integration tests for Entity graph indexing with real SQLiteGraphStore.

Verifies the full path: store_episodic → Entity node creation → graph traversal.
Uses real SQLiteGraphStore (in-memory via tempfile) instead of mocks to catch
bugs that mock-based tests miss (e.g. match_keys / properties mismatch).
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.toolkits.memory._internal.maintenance_enrichment import (
    enrich_with_graph,
)
from myrm_agent_harness.toolkits.memory._internal.storage import (
    store_episodic,
    store_episodics_batch,
)
from myrm_agent_harness.toolkits.memory.config import MemoryConfig
from myrm_agent_harness.toolkits.memory.graph.sqlite_store import SQLiteGraphStore
from myrm_agent_harness.toolkits.memory.protocols.vector import VectorDocument
from myrm_agent_harness.toolkits.memory.types import (
    EpisodicMemory,
    MemorySearchResult,
    MemoryType,
)


@pytest.fixture
def memory_config() -> MemoryConfig:
    return MemoryConfig(
        embedding_model="test-model",
        collection_prefix="test_memory",
        bm25_top_k=50,
        bm25_max_corpus_size=5000,
    )


@pytest.fixture
async def real_graph_store():
    """Create a real SQLiteGraphStore backed by a temp file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test_graph.db")
        store = SQLiteGraphStore(db_path)
        await store._get_connection()
        yield store
        await store.close()


@pytest.fixture
def mock_vector_store():
    store = AsyncMock()
    store.upsert = AsyncMock()
    return store


@pytest.fixture
def mock_embedding():
    embedding = AsyncMock()
    embedding.embed = AsyncMock(return_value=[0.1] * 768)
    embedding.embed_batch = AsyncMock(return_value=[[0.1] * 768])
    embedding.dimension = 768
    return embedding


@pytest.fixture
def mock_cache():
    cache = AsyncMock()
    cache.get = AsyncMock(return_value=None)
    cache.put = AsyncMock()
    cache.get_batch = AsyncMock(return_value=[None])
    cache.put_batch = AsyncMock()
    return cache


class TestEntityGraphCreation:
    """Verify Entity nodes are actually created with real SQLiteGraphStore."""

    @pytest.mark.asyncio
    async def test_store_episodic_creates_entity_nodes(
        self, real_graph_store, mock_vector_store, mock_embedding, mock_cache, memory_config
    ):
        """Entity nodes and MENTIONS relationships must be created successfully."""
        memory = EpisodicMemory(
            id="mem-1",
            content="Learning Python and Rust",
            related_entities=["Python", "Rust"],
            embedding=[0.1] * 768,
        )

        result = await store_episodic(
            memory=memory,
            vector=mock_vector_store,
            config=memory_config,
            embedding=mock_embedding,
            cache=mock_cache,
            graph=real_graph_store,
        )

        assert result.id == "mem-1"

        python_nodes = await real_graph_store.find_nodes(["Entity"], {"name": "Python"})
        assert len(python_nodes) == 1
        assert python_nodes[0].properties["name"] == "Python"

        rust_nodes = await real_graph_store.find_nodes(["Entity"], {"name": "Rust"})
        assert len(rust_nodes) == 1
        assert rust_nodes[0].properties["name"] == "Rust"

    @pytest.mark.asyncio
    async def test_entity_node_idempotency(
        self, real_graph_store, mock_vector_store, mock_embedding, mock_cache, memory_config
    ):
        """Storing two memories referencing the same entity must reuse the same Entity node."""
        mem1 = EpisodicMemory(
            id="mem-1", content="Python is great", related_entities=["Python"], embedding=[0.1] * 768
        )
        mem2 = EpisodicMemory(
            id="mem-2", content="Python tutorial", related_entities=["Python"], embedding=[0.2] * 768
        )

        await store_episodic(
            memory=mem1, vector=mock_vector_store, config=memory_config,
            embedding=mock_embedding, cache=mock_cache, graph=real_graph_store,
        )
        await store_episodic(
            memory=mem2, vector=mock_vector_store, config=memory_config,
            embedding=mock_embedding, cache=mock_cache, graph=real_graph_store,
        )

        python_nodes = await real_graph_store.find_nodes(["Entity"], {"name": "Python"})
        assert len(python_nodes) == 1, f"Expected 1 Entity node, got {len(python_nodes)}"

    @pytest.mark.asyncio
    async def test_graph_traversal_finds_related_memories(
        self, real_graph_store, mock_vector_store, mock_embedding, mock_cache, memory_config
    ):
        """Two memories linked by a shared Entity should be discoverable via graph traversal."""
        mem1 = EpisodicMemory(
            id="mem-chat1", content="Discussed Python frameworks", related_entities=["Python"], embedding=[0.1] * 768
        )
        mem2 = EpisodicMemory(
            id="mem-chat2", content="Python debugging tips", related_entities=["Python"], embedding=[0.2] * 768
        )

        await store_episodic(
            memory=mem1, vector=mock_vector_store, config=memory_config,
            embedding=mock_embedding, cache=mock_cache, graph=real_graph_store,
        )
        await store_episodic(
            memory=mem2, vector=mock_vector_store, config=memory_config,
            embedding=mock_embedding, cache=mock_cache, graph=real_graph_store,
        )

        related = await real_graph_store.get_related_nodes("mem-chat1", "MENTIONS")
        related_ids = set(related)
        assert "mem-chat2" in related_ids, f"Expected mem-chat2 in related, got {related_ids}"

    @pytest.mark.asyncio
    async def test_batch_store_creates_entities(
        self, real_graph_store, mock_vector_store, mock_embedding, mock_cache, memory_config
    ):
        """Batch storage must also create Entity nodes correctly."""
        memories = [
            EpisodicMemory(
                id="batch-1", content="Learning Go", related_entities=["Go"], embedding=[0.1] * 768
            ),
            EpisodicMemory(
                id="batch-2", content="Go concurrency", related_entities=["Go"], embedding=[0.2] * 768
            ),
            EpisodicMemory(
                id="batch-3", content="Rust vs Go", related_entities=["Rust", "Go"], embedding=[0.3] * 768
            ),
        ]

        mock_cache.get_batch.return_value = [None, None, None]

        await store_episodics_batch(
            memories=memories, vector=mock_vector_store, config=memory_config,
            embedding=mock_embedding, cache=mock_cache, graph=real_graph_store,
        )

        go_nodes = await real_graph_store.find_nodes(["Entity"], {"name": "Go"})
        assert len(go_nodes) == 1, f"Expected 1 Go Entity node, got {len(go_nodes)}"

        rust_nodes = await real_graph_store.find_nodes(["Entity"], {"name": "Rust"})
        assert len(rust_nodes) == 1

        related = await real_graph_store.get_related_nodes("batch-1", "MENTIONS")
        related_ids = set(related)
        assert "batch-2" in related_ids
        assert "batch-3" in related_ids


class TestGraphEnrichmentNamespaceFilter:
    """Verify namespace filtering in graph enrichment path."""

    @pytest.mark.asyncio
    async def test_namespace_filter_blocks_cross_namespace(self):
        """Graph enrichment must skip docs from non-matching namespaces."""
        mock_graph = AsyncMock()
        mock_vector = AsyncMock()

        seed_mem = EpisodicMemory(
            id="seed-1", content="Seed memory about Python",
            related_entities=["Python"], embedding=[0.1] * 768,
        )
        seed_result = MemorySearchResult(
            memory=seed_mem, score=0.9, memory_type=MemoryType.EPISODIC,
        )

        mock_graph.get_related_nodes_with_depth = AsyncMock(
            return_value=[("sibling-1", 1)]
        )
        mock_graph.find_nodes = AsyncMock(return_value=[])

        cross_ns_doc = VectorDocument(
            id="sibling-1",
            content="Python tips from other agent",
            embedding=[0.2] * 768,
            metadata={
                "memory_type": "episodic",
                "status": "active",
                "namespaces": ["agent:other-agent"],
                "primary_namespace": "agent:other-agent",
                "importance": 0.5,
                "timestamp": "2026-01-01T00:00:00",
                "created_at": "2026-01-01T00:00:00",
                "updated_at": "2026-01-01T00:00:00",
            },
        )
        mock_vector.get = AsyncMock(return_value=[cross_ns_doc])

        config = MemoryConfig(
            embedding_model="test", collection_prefix="test_memory",
            bm25_top_k=50, bm25_max_corpus_size=5000,
        )

        results = await enrich_with_graph(
            results=[seed_result],
            query="Python",
            limit=10,
            graph=mock_graph,
            vector=mock_vector,
            config=config,
            namespaces=["agent:my-agent"],
        )

        result_ids = {r.id for r in results}
        assert "sibling-1" not in result_ids, "Cross-namespace doc should be filtered out"

    @pytest.mark.asyncio
    async def test_namespace_filter_allows_matching_namespace(self):
        """Graph enrichment must include docs from matching namespaces."""
        mock_graph = AsyncMock()
        mock_vector = AsyncMock()

        seed_mem = EpisodicMemory(
            id="seed-1", content="Seed memory about Python",
            related_entities=["Python"], embedding=[0.1] * 768,
        )
        seed_result = MemorySearchResult(
            memory=seed_mem, score=0.9, memory_type=MemoryType.EPISODIC,
        )

        mock_graph.get_related_nodes_with_depth = AsyncMock(
            return_value=[("sibling-1", 1)]
        )
        mock_graph.find_nodes = AsyncMock(return_value=[])

        same_ns_doc = VectorDocument(
            id="sibling-1",
            content="Python debugging tips",
            embedding=[0.2] * 768,
            metadata={
                "memory_type": "episodic",
                "status": "active",
                "namespaces": ["agent:my-agent"],
                "primary_namespace": "agent:my-agent",
                "importance": 0.5,
                "timestamp": "2026-01-01T00:00:00",
                "created_at": "2026-01-01T00:00:00",
                "updated_at": "2026-01-01T00:00:00",
            },
        )
        mock_vector.get = AsyncMock(return_value=[same_ns_doc])

        config = MemoryConfig(
            embedding_model="test", collection_prefix="test_memory",
            bm25_top_k=50, bm25_max_corpus_size=5000,
        )

        results = await enrich_with_graph(
            results=[seed_result],
            query="Python",
            limit=10,
            graph=mock_graph,
            vector=mock_vector,
            config=config,
            namespaces=["agent:my-agent"],
        )

        result_ids = {r.id for r in results}
        assert "sibling-1" in result_ids, "Same-namespace doc should be included"

    @pytest.mark.asyncio
    async def test_no_namespace_filter_when_namespaces_none(self):
        """When namespaces is None, all docs should pass through."""
        mock_graph = AsyncMock()
        mock_vector = AsyncMock()

        seed_mem = EpisodicMemory(
            id="seed-1", content="Seed memory about Python",
            related_entities=["Python"], embedding=[0.1] * 768,
        )
        seed_result = MemorySearchResult(
            memory=seed_mem, score=0.9, memory_type=MemoryType.EPISODIC,
        )

        mock_graph.get_related_nodes_with_depth = AsyncMock(
            return_value=[("sibling-1", 1)]
        )
        mock_graph.find_nodes = AsyncMock(return_value=[])

        doc = VectorDocument(
            id="sibling-1",
            content="Python tips any namespace",
            embedding=[0.2] * 768,
            metadata={
                "memory_type": "episodic",
                "status": "active",
                "namespaces": ["agent:any"],
                "primary_namespace": "agent:any",
                "importance": 0.5,
                "timestamp": "2026-01-01T00:00:00",
                "created_at": "2026-01-01T00:00:00",
                "updated_at": "2026-01-01T00:00:00",
            },
        )
        mock_vector.get = AsyncMock(return_value=[doc])

        config = MemoryConfig(
            embedding_model="test", collection_prefix="test_memory",
            bm25_top_k=50, bm25_max_corpus_size=5000,
        )

        results = await enrich_with_graph(
            results=[seed_result],
            query="Python",
            limit=10,
            graph=mock_graph,
            vector=mock_vector,
            config=config,
            namespaces=None,
        )

        result_ids = {r.id for r in results}
        assert "sibling-1" in result_ids, "With namespaces=None, all docs should pass"


class TestStorageGraphEdgeCases:
    """Verify storage layer graph edge cases: graph=None, empty entities."""

    @pytest.mark.asyncio
    async def test_store_episodic_graph_none_succeeds(
        self, mock_vector_store, mock_embedding, mock_cache, memory_config
    ):
        """When graph=None, storage must succeed without attempting graph indexing."""
        memory = EpisodicMemory(
            id="mem-no-graph",
            content="No graph indexing needed",
            related_entities=["SomeEntity"],
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

        assert result.id == "mem-no-graph"
        mock_vector_store.upsert.assert_called_once()

    @pytest.mark.asyncio
    async def test_store_episodic_empty_entities_no_graph_call(
        self, real_graph_store, mock_vector_store, mock_embedding, mock_cache, memory_config
    ):
        """When related_entities is empty, no graph nodes should be created."""
        memory = EpisodicMemory(
            id="mem-empty-entities",
            content="No entities here",
            related_entities=[],
            embedding=[0.1] * 768,
        )

        result = await store_episodic(
            memory=memory,
            vector=mock_vector_store,
            config=memory_config,
            embedding=mock_embedding,
            cache=mock_cache,
            graph=real_graph_store,
        )

        assert result.id == "mem-empty-entities"
        all_nodes = await real_graph_store.find_nodes(["Entity"], {})
        assert len(all_nodes) == 0, "No Entity nodes should be created for empty related_entities"

    @pytest.mark.asyncio
    async def test_store_episodic_none_entities_no_graph_call(
        self, real_graph_store, mock_vector_store, mock_embedding, mock_cache, memory_config
    ):
        """When related_entities is None (default), no graph nodes should be created."""
        memory = EpisodicMemory(
            id="mem-none-entities",
            content="No entities",
            embedding=[0.1] * 768,
        )

        result = await store_episodic(
            memory=memory,
            vector=mock_vector_store,
            config=memory_config,
            embedding=mock_embedding,
            cache=mock_cache,
            graph=real_graph_store,
        )

        assert result.id == "mem-none-entities"

    @pytest.mark.asyncio
    async def test_batch_store_graph_none_succeeds(
        self, mock_vector_store, mock_embedding, mock_cache, memory_config
    ):
        """Batch storage with graph=None must succeed normally."""
        memories = [
            EpisodicMemory(
                id="batch-no-graph-1", content="Test batch",
                related_entities=["Entity1"], embedding=[0.1] * 768,
            ),
        ]

        result = await store_episodics_batch(
            memories=memories,
            vector=mock_vector_store,
            config=memory_config,
            embedding=mock_embedding,
            cache=mock_cache,
            graph=None,
        )

        assert len(result) == 1
        assert result[0].id == "batch-no-graph-1"

    @pytest.mark.asyncio
    async def test_batch_store_mixed_entities(
        self, real_graph_store, mock_vector_store, mock_embedding, mock_cache, memory_config
    ):
        """Batch with mix of entities and no-entities: only entity-bearing items get indexed."""
        memories = [
            EpisodicMemory(
                id="batch-has-entity", content="Python topic",
                related_entities=["Python"], embedding=[0.1] * 768,
            ),
            EpisodicMemory(
                id="batch-no-entity", content="General chat",
                related_entities=[], embedding=[0.2] * 768,
            ),
        ]

        mock_cache.get_batch.return_value = [None, None]

        await store_episodics_batch(
            memories=memories,
            vector=mock_vector_store,
            config=memory_config,
            embedding=mock_embedding,
            cache=mock_cache,
            graph=real_graph_store,
        )

        python_nodes = await real_graph_store.find_nodes(["Entity"], {"name": "Python"})
        assert len(python_nodes) == 1

        all_entity_nodes = await real_graph_store.find_nodes(["Entity"], {})
        assert len(all_entity_nodes) == 1, "Only Python entity should exist"
