from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.toolkits.memory._internal.maintenance import _search_claim_graph
from myrm_agent_harness.toolkits.memory.protocols.graph import GraphNode


@pytest.mark.asyncio
async def test_search_claim_graph():
    graph = AsyncMock()

    node1 = GraphNode(id="node1", labels=["Claim"], properties={
        "title": "Test Title",
        "claim_text": "Test Claim",
        "last_result": "Test Result",
        "evidence_count": 1,
        "freshness": "fresh",
        "contradiction_status": "none",
        "confidence": 0.9,
        "claim_key": "test_key",
        "primary_namespace": "test"
    })

    graph.find_nodes.return_value = [node1]

    results = await _search_claim_graph(
        graph,
        query="Test Title",
        current_channel_id="ch1",
        namespaces=["test"],
        limit=10
    )

    assert len(results) == 1
    assert results[0].id == "node1"
    assert results[0].score > 0

@pytest.mark.asyncio
async def test_search_claim_graph_no_tokens():
    graph = AsyncMock()

    results = await _search_claim_graph(
        graph,
        query="",
        current_channel_id="ch1",
        namespaces=["test"],
        limit=10
    )

    assert len(results) == 0

@pytest.mark.asyncio
async def test_search_claim_graph_no_nodes():
    graph = AsyncMock()
    graph.find_nodes.return_value = []

    results = await _search_claim_graph(
        graph,
        query="Test",
        current_channel_id="ch1",
        namespaces=["test"],
        limit=10
    )

    assert len(results) == 0
