"""Shared fixtures for memory toolkit tests."""

from unittest.mock import DEFAULT, AsyncMock

import pytest

from myrm_agent_harness.toolkits.memory.config import MemoryConfig


@pytest.fixture
def memory_config() -> MemoryConfig:
    """Create test memory configuration."""
    return MemoryConfig(
        embedding_model="test-model", collection_prefix="test_memory", bm25_top_k=50, bm25_max_corpus_size=5000
    )


@pytest.fixture
def mock_vector_store():
    """Create mock vector store."""
    store = AsyncMock()
    store.count = AsyncMock(return_value=10)
    store.scroll = AsyncMock()

    def _scroll_side_effect(*args, **kwargs):
        _ = args, kwargs
        payload = store.scroll._mock_return_value
        if payload is DEFAULT:
            return ([], None)
        if isinstance(payload, tuple) and len(payload) == 2:
            return payload
        return payload, None

    store.scroll.side_effect = _scroll_side_effect
    store.search = AsyncMock(return_value=[])
    store.upsert = AsyncMock()
    store.delete = AsyncMock()
    store.get = AsyncMock(return_value=None)
    store.close = AsyncMock()
    return store


@pytest.fixture
def mock_relational_store():
    """Create mock relational store."""
    store = AsyncMock()
    store.get_profile = AsyncMock(return_value=None)
    store.set_profile = AsyncMock()
    store.delete_profile = AsyncMock()
    store.list_profiles = AsyncMock(return_value=[])
    store.count_profiles = AsyncMock(return_value=0)
    store.create_rule = AsyncMock()
    store.get_rule = AsyncMock(return_value=None)
    store.list_rules = AsyncMock(return_value=[])
    store.count_rules = AsyncMock(return_value=0)
    store.search_rules = AsyncMock(return_value=[])
    store.submit_pending = AsyncMock(return_value="pending-1")
    store.get_pending = AsyncMock(return_value=None)
    store.pending_exists = AsyncMock(return_value=False)
    store.mark_pending = AsyncMock()
    store.list_pending = AsyncMock(return_value=[])
    store.count_pending = AsyncMock(return_value=0)
    store.batch_mark_pending = AsyncMock(return_value=3)
    store.close = AsyncMock()
    return store


@pytest.fixture
def mock_embedding():
    """Create mock embedding protocol."""
    embedding = AsyncMock()
    embedding.embed = AsyncMock(return_value=[0.1] * 768)
    embedding.embed_batch = AsyncMock(return_value=[[0.1] * 768])
    embedding.dimension = 768
    return embedding


@pytest.fixture
def mock_cache():
    """Create mock embedding cache."""
    cache = AsyncMock()
    cache.get = AsyncMock(return_value=None)
    cache.put = AsyncMock()
    cache.get_batch = AsyncMock(return_value=[None, None, None])
    cache.put_batch = AsyncMock()
    return cache


@pytest.fixture
def mock_graph_store():
    """Create mock graph store."""
    from myrm_agent_harness.toolkits.memory.protocols.graph import GraphNode, GraphRelationship

    store = AsyncMock()
    store.create_node = AsyncMock(return_value=GraphNode(id="node-1", labels=["EpisodicMemory"], properties={}))
    store.get_or_create_node = AsyncMock(return_value=GraphNode(id="entity-1", labels=["Entity"], properties={}))
    store.create_relationship = AsyncMock(
        return_value=GraphRelationship(
            id="rel-1", start_id="node-1", end_id="entity-1", rel_type="MENTIONS", properties={}
        )
    )
    store.get_node = AsyncMock(return_value=None)
    store.find_nodes = AsyncMock(return_value=[])
    store.update_node_properties = AsyncMock(
        side_effect=lambda node_id, properties: GraphNode(id=node_id, labels=["Entity"], properties=properties)
    )
    store.get_related_nodes = AsyncMock(return_value=[])
    store.delete_node = AsyncMock(return_value=True)
    store.delete_subgraph = AsyncMock(return_value=3)
    store.delete_all_by_owner = AsyncMock(return_value=10)
    store.health_check = AsyncMock(return_value=True)
    store.close = AsyncMock()
    return store
