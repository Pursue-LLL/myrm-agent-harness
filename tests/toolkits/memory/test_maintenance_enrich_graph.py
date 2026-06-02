from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.toolkits.memory._internal.maintenance import enrich_with_graph
from myrm_agent_harness.toolkits.memory.config import MemoryConfig
from myrm_agent_harness.toolkits.memory.protocols.vector import VectorDocument
from myrm_agent_harness.toolkits.memory.types import EpisodicMemory, MemorySearchResult, MemoryType


@pytest.mark.asyncio
async def test_enrich_with_graph():
    config = MemoryConfig(embedding_model="test")
    vector = AsyncMock()
    graph = AsyncMock()

    mem1 = EpisodicMemory(id="mem1", content="test", metadata={})
    res1 = MemorySearchResult(memory=mem1, score=0.9, memory_type=MemoryType.EPISODIC)

    graph.get_related_nodes_with_depth.return_value = [("mem2", 1)]

    doc2 = VectorDocument(id="mem2", content="query test", metadata={"status": "active"}, embedding=[0.1])
    vector.get.return_value = [doc2]

    results = await enrich_with_graph([res1], "query", 10, graph, vector, config)

    assert len(results) == 2
    assert results[0].id == "mem1"
    assert results[1].id == "mem2"
    # Unified scoring: token overlap (1 match) + freshness + importance + channel
    assert results[1].score > 0.0


@pytest.mark.asyncio
async def test_enrich_with_graph_no_vector():
    config = MemoryConfig(embedding_model="test")
    graph = AsyncMock()

    mem1 = EpisodicMemory(id="mem1", content="test", metadata={})
    res1 = MemorySearchResult(memory=mem1, score=0.9, memory_type=MemoryType.EPISODIC)

    results = await enrich_with_graph([res1], "query", 10, graph, None, config)

    assert len(results) == 1
    assert results[0].id == "mem1"


@pytest.mark.asyncio
async def test_enrich_with_graph_claim_graph_error():
    config = MemoryConfig(embedding_model="test")
    vector = AsyncMock()
    graph = AsyncMock()

    graph.query.side_effect = Exception("Claim graph error")

    mem1 = EpisodicMemory(id="mem1", content="test", metadata={})
    res1 = MemorySearchResult(memory=mem1, score=0.9, memory_type=MemoryType.EPISODIC)

    results = await enrich_with_graph([res1], "query", 10, graph, vector, config)

    assert len(results) >= 1
    assert results[0].id == "mem1"


@pytest.mark.asyncio
async def test_enrich_with_graph_vector_get_error():
    config = MemoryConfig(embedding_model="test")
    vector = AsyncMock()
    graph = AsyncMock()

    mem1 = EpisodicMemory(id="mem1", content="test", metadata={})
    res1 = MemorySearchResult(memory=mem1, score=0.9, memory_type=MemoryType.EPISODIC)

    graph.get_related_nodes_with_depth.return_value = [("mem2", 1)]
    vector.get.side_effect = Exception("Vector get error")

    results = await enrich_with_graph([res1], "query", 10, graph, vector, config)

    assert len(results) == 1
    assert results[0].id == "mem1"
