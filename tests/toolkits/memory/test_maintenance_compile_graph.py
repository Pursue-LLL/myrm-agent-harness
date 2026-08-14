from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.toolkits.memory._internal.maintenance import compile_claim_graph
from myrm_agent_harness.toolkits.memory.config import MemoryConfig
from myrm_agent_harness.toolkits.memory.protocols.graph import GraphNode
from myrm_agent_harness.toolkits.memory.protocols.vector import VectorDocument


@pytest.mark.asyncio
async def test_compile_claim_graph():
    config = MemoryConfig(embedding_model="test")
    vector = AsyncMock()
    graph = AsyncMock()

    content = """
Title: Test Title
Goal: Test Goal
Result: Test Result
Change Kind: ADD
Key Details: Test Details
"""

    doc = VectorDocument(
        id="doc1",
        content=content,
        metadata={"importance": 0.9, "primary_namespace": "test", "channel_id": "ch1"},
        embedding=[0.1],
        created_at=datetime.now(UTC),
    )

    vector.scroll.side_effect = [([doc], None)]

    evidence_node = GraphNode(id="ev1", labels=["Evidence"], properties={})
    claim_node = GraphNode(
        id="cl1",
        labels=["Claim"],
        properties={"evidence_count": 0, "result_polarity": "positive", "contradiction_count": 0, "goal": "Test Goal"},
    )

    graph.get_or_create_node.side_effect = [evidence_node, claim_node]
    graph.update_node_properties.return_value = claim_node

    result = await compile_claim_graph(vector, graph, config)

    assert result == 1
    assert graph.get_or_create_node.call_count == 2
    graph.create_relationship.assert_called_once()
    vector.upsert.assert_called_once()

    upserted_docs = vector.upsert.call_args[0][1]
    assert upserted_docs[0].metadata["claim_graph_state"] == "compiled"


@pytest.mark.asyncio
async def test_compile_claim_graph_no_docs():
    config = MemoryConfig(embedding_model="test")
    vector = AsyncMock()
    graph = AsyncMock()

    vector.scroll.side_effect = [([], None)]

    result = await compile_claim_graph(vector, graph, config)

    assert result == 0


@pytest.mark.asyncio
async def test_compile_claim_graph_scoped_to_namespaces():
    """Claim compilation must restrict its scan to the given namespaces.

    A maintenance pipeline for one agent scope must never compile claims
    from digests owned by other scopes in the same collection.
    """
    config = MemoryConfig(embedding_model="test")
    vector = AsyncMock()
    graph = AsyncMock()

    expected_namespaces = ["global:test-user", "agent:test-agent"]

    async def _scroll(*args, **kwargs):
        seen = kwargs.get("filters", {})
        assert seen.get("primary_namespace") == expected_namespaces
        return [], None

    vector.scroll.side_effect = _scroll

    result = await compile_claim_graph(vector, graph, config, namespaces=expected_namespaces)

    assert result == 0
    vector.scroll.assert_awaited()


@pytest.mark.asyncio
async def test_compile_claim_graph_namespaces_none_keeps_unscoped_filter():
    """namespaces=None (default) must keep the historical unscoped filter."""
    config = MemoryConfig(embedding_model="test")
    vector = AsyncMock()
    graph = AsyncMock()

    seen_filters: dict[str, object] = {}

    async def _scroll(*args, **kwargs):
        seen_filters.update(kwargs.get("filters", {}))
        return [], None

    vector.scroll.side_effect = _scroll

    result = await compile_claim_graph(vector, graph, config)

    assert result == 0
    assert "primary_namespace" not in seen_filters
