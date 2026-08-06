"""Integration test: claim search namespace isolation with real SQLiteGraphStore.

Verifies the full pipeline: real SQL queries, real json_extract index,
real namespace pre-filtering — no mocks on the graph layer.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.memory._internal.maintenance import _search_claim_graph
from myrm_agent_harness.toolkits.memory.graph import SQLiteGraphStore


def _claim_props(namespace: str, title: str, claim_text: str) -> dict[str, str | int | float]:
    return {
        "primary_namespace": namespace,
        "title": title,
        "claim_text": claim_text,
        "last_result": "completed",
        "evidence_count": 1,
        "freshness": "fresh",
        "contradiction_status": "none",
        "confidence": 0.9,
        "claim_key": f"key_{title}",
    }


@pytest.fixture
async def graph(tmp_path: Path) -> SQLiteGraphStore:
    store = SQLiteGraphStore(str(tmp_path / "test_ns.db"))
    yield store  # type: ignore[misc]
    await store.close()


@pytest.mark.asyncio
async def test_namespace_isolation_real_sqlite(graph: SQLiteGraphStore) -> None:
    """With real SQLite, namespace-filtered search only returns matching claims."""
    await graph.create_node(["Claim"], _claim_props("agent:alice", "Alice deploy", "Alice deploy service"))
    await graph.create_node(["Claim"], _claim_props("agent:alice", "Alice deploy fix", "Alice deploy hotfix"))
    await graph.create_node(["Claim"], _claim_props("agent:bob", "Bob deploy", "Bob deploy pipeline"))
    await graph.create_node(["Claim"], _claim_props("global", "Shared deploy", "Shared deploy insight"))

    alice_results = await _search_claim_graph(
        graph, query="deploy", current_channel_id=None, namespaces=["agent:alice"], limit=10,
    )
    alice_titles = {r.memory.title for r in alice_results}
    assert "Alice deploy" in alice_titles
    assert "Alice deploy fix" in alice_titles
    assert "Bob deploy" not in alice_titles

    bob_results = await _search_claim_graph(
        graph, query="deploy", current_channel_id=None, namespaces=["agent:bob"], limit=10,
    )
    bob_titles = {r.memory.title for r in bob_results}
    assert "Bob deploy" in bob_titles
    assert "Alice deploy" not in bob_titles


@pytest.mark.asyncio
async def test_multi_namespace_merges_correctly(graph: SQLiteGraphStore) -> None:
    """Multi-namespace search merges results from each namespace without duplicates."""
    await graph.create_node(["Claim"], _claim_props("agent:alice", "Alice metric", "Alice metric analysis"))
    await graph.create_node(["Claim"], _claim_props("global", "Global metric", "Global metric overview"))
    await graph.create_node(["Claim"], _claim_props("agent:bob", "Bob metric", "Bob metric report"))

    results = await _search_claim_graph(
        graph, query="metric", current_channel_id=None, namespaces=["agent:alice", "global"], limit=10,
    )
    titles = {r.memory.title for r in results}
    assert "Alice metric" in titles
    assert "Global metric" in titles
    assert "Bob metric" not in titles


@pytest.mark.asyncio
async def test_none_namespace_returns_all(graph: SQLiteGraphStore) -> None:
    """With namespaces=None, all claims are returned regardless of namespace."""
    await graph.create_node(["Claim"], _claim_props("agent:alice", "Alice claim", "Alice data"))
    await graph.create_node(["Claim"], _claim_props("agent:bob", "Bob claim", "Bob data"))

    results = await _search_claim_graph(
        graph, query="claim data", current_channel_id=None, namespaces=None, limit=10,
    )
    assert len(results) == 2


@pytest.mark.asyncio
async def test_candidate_crowding_prevented(graph: SQLiteGraphStore) -> None:
    """Namespace pre-filtering prevents candidate crowding by other namespaces.

    Create many claims in agent:bob (flood), few in agent:alice.
    With pre-filtering, agent:alice claims are found despite bob's flood.
    """
    for i in range(50):
        await graph.create_node(["Claim"], _claim_props("agent:bob", f"Bob item {i}", f"Bob repetitive task {i}"))

    await graph.create_node(["Claim"], _claim_props("agent:alice", "Alice rare item", "Alice unique rare task"))

    results = await _search_claim_graph(
        graph, query="task", current_channel_id=None, namespaces=["agent:alice"], limit=5,
    )
    titles = {r.memory.title for r in results}
    assert "Alice rare item" in titles
    assert all("Bob" not in t for t in titles)


@pytest.mark.asyncio
async def test_limit_enforced_after_multi_namespace_merge(graph: SQLiteGraphStore) -> None:
    """Results from multiple namespaces are merged, score-sorted, then limited."""
    for i in range(10):
        await graph.create_node(
            ["Claim"],
            _claim_props("agent:alice", f"Alice task {i}", f"Alice important task {i}"),
        )
    for i in range(10):
        await graph.create_node(
            ["Claim"],
            _claim_props("global", f"Global task {i}", f"Global critical task {i}"),
        )

    results = await _search_claim_graph(
        graph, query="task", current_channel_id=None,
        namespaces=["agent:alice", "global"], limit=5,
    )
    assert len(results) <= 5
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True), "Results must be sorted by score descending"


@pytest.mark.asyncio
async def test_no_matching_query_returns_empty(graph: SQLiteGraphStore) -> None:
    """Claims exist but query has zero token overlap — returns empty."""
    await graph.create_node(["Claim"], _claim_props("agent:alice", "Python coding", "Python programming language"))

    results = await _search_claim_graph(
        graph, query="basketball", current_channel_id=None, namespaces=["agent:alice"], limit=10,
    )
    assert len(results) == 0


@pytest.mark.asyncio
async def test_empty_namespace_list_returns_all(graph: SQLiteGraphStore) -> None:
    """Empty list [] behaves same as None — unfiltered fallback."""
    await graph.create_node(["Claim"], _claim_props("agent:alice", "Alice code", "Alice code review"))
    await graph.create_node(["Claim"], _claim_props("agent:bob", "Bob code", "Bob code deploy"))

    results = await _search_claim_graph(
        graph, query="code", current_channel_id=None, namespaces=[], limit=10,
    )
    titles = {r.memory.title for r in results}
    assert "Alice code" in titles
    assert "Bob code" in titles
