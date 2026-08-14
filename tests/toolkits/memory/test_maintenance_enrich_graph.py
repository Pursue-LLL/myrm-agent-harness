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


@pytest.mark.asyncio
async def test_enrich_skips_archived_docs():
    """Docs with status=archived must be filtered out during enrichment."""
    config = MemoryConfig(embedding_model="test")
    vector = AsyncMock()
    graph = AsyncMock()

    mem1 = EpisodicMemory(id="mem1", content="test query", metadata={})
    res1 = MemorySearchResult(memory=mem1, score=0.9, memory_type=MemoryType.EPISODIC)

    graph.get_related_nodes_with_depth.return_value = [("mem2", 1)]

    archived_doc = VectorDocument(
        id="mem2",
        content="query test archived",
        metadata={"status": "archived"},
        embedding=[0.1],
    )
    vector.get.return_value = [archived_doc]

    results = await enrich_with_graph([res1], "query", 10, graph, vector, config)
    result_ids = {r.id for r in results}
    assert "mem2" not in result_ids


@pytest.mark.asyncio
async def test_enrich_skips_disabled_docs():
    """Docs with status=disabled must be filtered out during enrichment."""
    config = MemoryConfig(embedding_model="test")
    vector = AsyncMock()
    graph = AsyncMock()

    mem1 = EpisodicMemory(id="mem1", content="test query", metadata={})
    res1 = MemorySearchResult(memory=mem1, score=0.9, memory_type=MemoryType.EPISODIC)

    graph.get_related_nodes_with_depth.return_value = [("mem2", 1)]

    disabled_doc = VectorDocument(
        id="mem2",
        content="query test disabled",
        metadata={"status": "disabled"},
        embedding=[0.1],
    )
    vector.get.return_value = [disabled_doc]

    results = await enrich_with_graph([res1], "query", 10, graph, vector, config)
    result_ids = {r.id for r in results}
    assert "mem2" not in result_ids


@pytest.mark.asyncio
async def test_enrich_skips_archived_flag_docs():
    """Docs with metadata.archived=True must be filtered out."""
    config = MemoryConfig(embedding_model="test")
    vector = AsyncMock()
    graph = AsyncMock()

    mem1 = EpisodicMemory(id="mem1", content="test query", metadata={})
    res1 = MemorySearchResult(memory=mem1, score=0.9, memory_type=MemoryType.EPISODIC)

    graph.get_related_nodes_with_depth.return_value = [("mem2", 1)]

    archived_flag_doc = VectorDocument(
        id="mem2",
        content="query test flagged",
        metadata={"status": "active", "archived": True},
        embedding=[0.1],
    )
    vector.get.return_value = [archived_flag_doc]

    results = await enrich_with_graph([res1], "query", 10, graph, vector, config)
    result_ids = {r.id for r in results}
    assert "mem2" not in result_ids


@pytest.mark.asyncio
async def test_enrich_deduplicates_same_content():
    """Two siblings with same content but different IDs should be deduplicated."""
    config = MemoryConfig(embedding_model="test")
    vector = AsyncMock()
    graph = AsyncMock()

    mem1 = EpisodicMemory(id="mem1", content="python query", metadata={})
    res1 = MemorySearchResult(memory=mem1, score=0.9, memory_type=MemoryType.EPISODIC)

    graph.get_related_nodes_with_depth.return_value = [("mem2", 1), ("mem3", 1)]

    doc2 = VectorDocument(
        id="mem2",
        content="Python query tutorial",
        metadata={"status": "active"},
        embedding=[0.1],
    )
    doc3 = VectorDocument(
        id="mem3",
        content="python query tutorial",
        metadata={"status": "active"},
        embedding=[0.2],
    )
    vector.get.return_value = [doc2, doc3]

    results = await enrich_with_graph([res1], "query python", 10, graph, vector, config)
    sibling_ids = {r.id for r in results if r.id != "mem1"}
    assert len(sibling_ids) == 1, f"Expected 1 sibling after dedup, got {len(sibling_ids)}: {sibling_ids}"


@pytest.mark.asyncio
async def test_enrich_respects_sibling_limit():
    """Number of siblings retrieved must not exceed graph_sibling_limit (no namespaces)."""
    config = MemoryConfig(embedding_model="test", graph_sibling_limit=2)
    vector = AsyncMock()
    graph = AsyncMock()

    mem1 = EpisodicMemory(id="mem1", content="test query", metadata={})
    res1 = MemorySearchResult(memory=mem1, score=0.9, memory_type=MemoryType.EPISODIC)

    graph.get_related_nodes_with_depth.return_value = [
        ("mem2", 1),
        ("mem3", 1),
        ("mem4", 1),
        ("mem5", 2),
    ]

    docs = [
        VectorDocument(id=f"mem{i}", content=f"query test doc {i}", metadata={"status": "active"}, embedding=[0.1])
        for i in range(2, 6)
    ]
    vector.get.return_value = docs

    await enrich_with_graph([res1], "query", 10, graph, vector, config)

    vector.get.assert_called_once()
    requested_ids = vector.get.call_args[0][1]
    assert len(requested_ids) <= 2, f"Should request at most 2 siblings, got {len(requested_ids)}"


@pytest.mark.asyncio
async def test_enrich_overfetch_with_namespaces():
    """With namespaces, candidate pool is sibling_limit*3 to survive namespace filtering."""
    config = MemoryConfig(embedding_model="test", graph_sibling_limit=2)
    vector = AsyncMock()
    graph = AsyncMock()

    mem1 = EpisodicMemory(id="mem1", content="test query", metadata={})
    res1 = MemorySearchResult(memory=mem1, score=0.9, memory_type=MemoryType.EPISODIC)

    graph.get_related_nodes_with_depth.return_value = [
        ("m2", 1),
        ("m3", 1),
        ("m4", 1),
        ("m5", 1),
        ("m6", 1),
        ("m7", 2),
    ]

    docs = [
        VectorDocument(
            id=f"m{i}",
            content=f"query test doc {i}",
            metadata={"status": "active", "namespaces": ["work"]},
            embedding=[0.1],
        )
        for i in range(2, 8)
    ]
    vector.get.return_value = docs

    await enrich_with_graph(
        [res1],
        "query",
        10,
        graph,
        vector,
        config,
        namespaces=["work"],
    )

    vector.get.assert_called_once()
    requested_ids = vector.get.call_args[0][1]
    assert len(requested_ids) <= 6, f"Over-fetch should be sibling_limit*3=6, got {len(requested_ids)}"
    assert len(requested_ids) > 2, f"Over-fetch should exceed sibling_limit=2, got {len(requested_ids)}"


@pytest.mark.asyncio
async def test_enrich_namespace_filter_excludes_cross_namespace():
    """Siblings from other namespaces should be filtered out after over-fetch."""
    config = MemoryConfig(embedding_model="test", graph_sibling_limit=10)
    vector = AsyncMock()
    graph = AsyncMock()

    mem1 = EpisodicMemory(id="mem1", content="test query", metadata={})
    res1 = MemorySearchResult(memory=mem1, score=0.9, memory_type=MemoryType.EPISODIC)

    graph.get_related_nodes_with_depth.return_value = [("m2", 1), ("m3", 1)]

    docs = [
        VectorDocument(
            id="m2",
            content="query test same ns",
            metadata={"status": "active", "namespaces": ["work"]},
            embedding=[0.1],
        ),
        VectorDocument(
            id="m3",
            content="query test other ns",
            metadata={"status": "active", "namespaces": ["personal"]},
            embedding=[0.1],
        ),
    ]
    vector.get.return_value = docs

    results = await enrich_with_graph(
        [res1],
        "query",
        10,
        graph,
        vector,
        config,
        namespaces=["work"],
    )

    result_ids = {r.id for r in results}
    assert "m2" in result_ids
    assert "m3" not in result_ids


@pytest.mark.asyncio
async def test_enrich_depth_sorting_prefers_direct():
    """Direct siblings (depth=1) should be preferred over 2-hop (depth=2) when limited."""
    config = MemoryConfig(embedding_model="test", graph_sibling_limit=2)
    vector = AsyncMock()
    graph = AsyncMock()

    mem1 = EpisodicMemory(id="mem1", content="test query", metadata={})
    res1 = MemorySearchResult(memory=mem1, score=0.9, memory_type=MemoryType.EPISODIC)

    graph.get_related_nodes_with_depth.return_value = [
        ("deep1", 2),
        ("direct1", 1),
        ("deep2", 2),
        ("direct2", 1),
    ]

    vector.get.return_value = []

    await enrich_with_graph([res1], "query", 10, graph, vector, config)

    requested_ids = vector.get.call_args[0][1]
    assert set(requested_ids) == {"direct1", "direct2"}
