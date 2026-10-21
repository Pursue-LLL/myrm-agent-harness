from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.toolkits.memory._internal.maintenance import _search_claim_graph
from myrm_agent_harness.toolkits.memory.protocols.graph import GraphNode


def _make_claim_node(node_id: str, title: str, namespace: str = "test", **extra: str | int | float) -> GraphNode:
    props: dict[str, str | int | float] = {
        "title": title,
        "claim_text": f"Claim about {title}",
        "last_result": "completed",
        "evidence_count": 1,
        "freshness": "fresh",
        "contradiction_status": "none",
        "confidence": 0.9,
        "claim_key": f"key_{node_id}",
        "primary_namespace": namespace,
    }
    props.update(extra)
    return GraphNode(id=node_id, labels=["Claim"], properties=props)


@pytest.mark.asyncio
async def test_search_claim_graph():
    graph = AsyncMock()
    graph.find_nodes.return_value = [_make_claim_node("node1", "Test Title")]

    results = await _search_claim_graph(
        graph,
        query="Test Title",
        current_channel_id="ch1",
        namespaces=["test"],
        limit=10,
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
        limit=10,
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
        limit=10,
    )

    assert len(results) == 0


@pytest.mark.asyncio
async def test_search_claim_graph_namespace_pre_filtering():
    """With namespaces, find_nodes is called per-namespace with primary_namespace filter."""
    graph = AsyncMock()
    graph.find_nodes.return_value = [
        _make_claim_node("n1", "Python coding", namespace="work"),
    ]

    results = await _search_claim_graph(
        graph,
        query="Python",
        current_channel_id="ch1",
        namespaces=["work"],
        limit=10,
    )

    graph.find_nodes.assert_called_once_with(
        ["Claim"],
        {"primary_namespace": "work"},
        limit=500,
    )
    assert len(results) == 1
    assert results[0].id == "n1"


@pytest.mark.asyncio
async def test_search_claim_graph_multi_namespace_dedup():
    """Multiple namespaces: find_nodes called per-namespace, results deduped by ID."""
    graph = AsyncMock()
    shared_node = _make_claim_node("shared", "Python topic", namespace="ns_a")
    graph.find_nodes.side_effect = [
        [_make_claim_node("a1", "Python coding", namespace="ns_a"), shared_node],
        [_make_claim_node("b1", "Python tutorial", namespace="ns_b"), shared_node],
    ]

    results = await _search_claim_graph(
        graph,
        query="Python",
        current_channel_id="ch1",
        namespaces=["ns_a", "ns_b"],
        limit=10,
    )

    assert graph.find_nodes.call_count == 2
    result_ids = {r.id for r in results}
    assert "a1" in result_ids
    assert "b1" in result_ids
    assert "shared" in result_ids
    assert len(result_ids) == 3


@pytest.mark.asyncio
async def test_search_claim_graph_namespace_none_returns_all():
    """When namespaces is None, find_nodes is called with empty filters."""
    graph = AsyncMock()
    graph.find_nodes.return_value = [
        _make_claim_node("n1", "Task Alpha", namespace="ns_a"),
        _make_claim_node("n2", "Task Beta", namespace="ns_b"),
    ]

    results = await _search_claim_graph(
        graph,
        query="Task",
        current_channel_id="ch1",
        namespaces=None,
        limit=10,
    )

    graph.find_nodes.assert_called_once_with(["Claim"], {}, limit=500)
    assert len(results) == 2


@pytest.mark.asyncio
async def test_search_claim_graph_empty_namespace_list_returns_all():
    """When namespaces is empty list, falls back to unfiltered query."""
    graph = AsyncMock()
    graph.find_nodes.return_value = [
        _make_claim_node("n1", "Task item", namespace="any"),
    ]

    results = await _search_claim_graph(
        graph,
        query="Task",
        current_channel_id="ch1",
        namespaces=[],
        limit=10,
    )

    graph.find_nodes.assert_called_once_with(["Claim"], {}, limit=500)
    assert len(results) == 1


@pytest.mark.asyncio
async def test_search_claim_graph_candidate_limit_calculation():
    """Verify find_nodes is called with candidate_limit = max(limit * 8, 500)."""
    graph = AsyncMock()
    graph.find_nodes.return_value = []

    await _search_claim_graph(
        graph,
        query="test query",
        current_channel_id="ch1",
        namespaces=["test"],
        limit=10,
    )
    call_kwargs = graph.find_nodes.call_args
    assert call_kwargs[1]["limit"] == 500  # max(10*8=80, 500) = 500

    graph.reset_mock()
    graph.find_nodes.return_value = []
    await _search_claim_graph(
        graph,
        query="test query",
        current_channel_id="ch1",
        namespaces=["test"],
        limit=100,
    )
    call_kwargs = graph.find_nodes.call_args
    assert call_kwargs[1]["limit"] == 800  # max(100*8=800, 500) = 800


@pytest.mark.asyncio
async def test_search_claim_graph_zero_score_excluded():
    """Nodes that don't match query tokens at all should have score <= 0 and be excluded."""
    graph = AsyncMock()
    graph.find_nodes.return_value = [
        _make_claim_node("n1", "Swimming exercise", namespace="test"),
    ]

    results = await _search_claim_graph(
        graph,
        query="completely unrelated database migration topic",
        current_channel_id="ch1",
        namespaces=["test"],
        limit=10,
    )

    assert len(results) == 0


@pytest.mark.asyncio
async def test_search_claim_graph_respects_limit():
    """Results should be truncated to the requested limit."""
    graph = AsyncMock()
    nodes = [_make_claim_node(f"n{i}", f"Topic keyword {i}", namespace="test") for i in range(20)]
    graph.find_nodes.return_value = nodes

    results = await _search_claim_graph(
        graph,
        query="Topic keyword",
        current_channel_id="ch1",
        namespaces=["test"],
        limit=5,
    )

    assert len(results) <= 5


@pytest.mark.asyncio
async def test_search_claim_graph_cjk_query():
    """CJK queries should match CJK claim titles via single-character tokens."""
    graph = AsyncMock()
    graph.find_nodes.return_value = [
        _make_claim_node("cn1", "完成用户登录功能重构", claim_text="用户登录模块从session迁移到JWT"),
    ]

    results = await _search_claim_graph(
        graph,
        query="用户登录",
        current_channel_id="ch1",
        namespaces=["test"],
        limit=10,
    )

    assert len(results) == 1
    assert results[0].score > 0


@pytest.mark.asyncio
async def test_search_claim_graph_cjk_no_match():
    """CJK queries that don't overlap should return empty."""
    graph = AsyncMock()
    graph.find_nodes.return_value = [
        _make_claim_node("cn1", "完成用户登录功能重构", claim_text="用户登录模块从session迁移到JWT"),
    ]

    results = await _search_claim_graph(
        graph,
        query="数据库备份策略",
        current_channel_id="ch1",
        namespaces=["test"],
        limit=10,
    )

    assert len(results) == 0


@pytest.mark.asyncio
async def test_search_claim_graph_mixed_cjk_english():
    """Mixed CJK+English titles should be searchable by either language."""
    graph = AsyncMock()
    graph.find_nodes.return_value = [
        _make_claim_node("mix1", "配置Nginx反向代理", claim_text="Nginx reverse proxy configuration"),
    ]

    results_en = await _search_claim_graph(
        graph,
        query="nginx",
        current_channel_id="ch1",
        namespaces=["test"],
        limit=10,
    )
    assert len(results_en) == 1

    results_cn = await _search_claim_graph(
        graph,
        query="配置代理",
        current_channel_id="ch1",
        namespaces=["test"],
        limit=10,
    )
    assert len(results_cn) == 1
