"""SQLiteGraphStore unit tests — CRUD, traversal, lifecycle, edge cases."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.memory.graph import SQLiteGraphStore
from myrm_agent_harness.toolkits.memory.graph.exceptions import (
    GraphConnectionError,
    GraphNotSupportedError,
    GraphQueryError,
)
from myrm_agent_harness.toolkits.memory.protocols.graph import GraphStoreProtocol


@pytest.fixture
async def store(tmp_path: Path) -> SQLiteGraphStore:
    s = SQLiteGraphStore(str(tmp_path / "test_graph.db"))
    yield s  # type: ignore[misc]
    await s.close()


# ── Protocol satisfaction ────────────────────────────────────────────


def test_satisfies_protocol() -> None:
    with tempfile.TemporaryDirectory() as d:
        s = SQLiteGraphStore(str(Path(d) / "proto.db"))
        assert isinstance(s, GraphStoreProtocol)


# ── CRUD ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_and_get_node(store: SQLiteGraphStore) -> None:
    node = await store.create_node(
        labels=["Memory"],
        properties={
            "id": "mem_1",
            "content": "hello",
        },
    )
    assert node.id == "mem_1"
    assert node.labels == ["Memory"]
    assert node.properties["content"] == "hello"

    fetched = await store.get_node("mem_1")
    assert fetched is not None
    assert fetched.id == "mem_1"


@pytest.mark.asyncio
async def test_get_node_not_found(store: SQLiteGraphStore) -> None:
    result = await store.get_node("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_get_or_create_node_idempotent(store: SQLiteGraphStore) -> None:
    props = {
        "name": "Python",
    }
    n1 = await store.get_or_create_node(["Entity"], ["name"], props)
    n2 = await store.get_or_create_node(["Entity"], ["name"], props)
    assert n1.id == n2.id


@pytest.mark.asyncio
async def test_find_nodes_by_properties(store: SQLiteGraphStore) -> None:
    await store.create_node(["Claim"], {"id": "c1", "claim_key": "auth-task"})
    await store.create_node(["Claim"], {"id": "c2", "claim_key": "billing-task"})
    await store.create_node(["Claim"], {"id": "c3", "claim_key": "auth-task"})

    results = await store.find_nodes(["Claim"], {}, limit=10)
    result_ids = {node.id for node in results}

    assert result_ids == {"c1", "c2", "c3"}


@pytest.mark.asyncio
async def test_update_node_properties_merges_existing(store: SQLiteGraphStore) -> None:
    await store.create_node(["Claim"], {"id": "c1", "freshness": "stale"})

    updated = await store.update_node_properties("c1", {"freshness": "fresh", "evidence_count": 2})

    assert updated is not None
    assert updated.properties["freshness"] == "fresh"
    assert updated.properties["evidence_count"] == 2


@pytest.mark.asyncio
async def test_create_relationship(store: SQLiteGraphStore) -> None:
    n1 = await store.create_node(["A"], {"id": "a1"})
    n2 = await store.create_node(["B"], {"id": "b1"})
    rel = await store.create_relationship(n1.id, n2.id, "LINKS", {"weight": 0.9})
    assert rel.start_id == "a1"
    assert rel.end_id == "b1"
    assert rel.rel_type == "LINKS"
    assert rel.properties["weight"] == 0.9


# ── Delete ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_node_cascades_relationships(store: SQLiteGraphStore) -> None:
    n1 = await store.create_node(["A"], {"id": "a1"})
    n2 = await store.create_node(["B"], {"id": "b1"})
    await store.create_relationship(n1.id, n2.id, "REL")
    deleted = await store.delete_node("a1")
    assert deleted is True
    assert await store.get_node("a1") is None


@pytest.mark.asyncio
async def test_delete_node_nonexistent(store: SQLiteGraphStore) -> None:
    deleted = await store.delete_node("ghost")
    assert deleted is False


@pytest.mark.asyncio
async def test_delete_subgraph(store: SQLiteGraphStore) -> None:
    await store.create_node(
        ["Memory"],
        {
            "id": "m1",
        },
    )
    await store.create_node(["Entity"], {"id": "e1"})
    await store.create_relationship("m1", "e1", "MENTIONS")
    count = await store.delete_subgraph("m1")
    assert count >= 2  # 1 node + at least 1 relationship
    assert await store.get_node("m1") is None


@pytest.mark.asyncio
async def test_delete_all_by_owner(store: SQLiteGraphStore) -> None:
    await store.create_node(["Memory"], {"id": "m1", "user_id": "alice"})
    await store.create_node(["Memory"], {"id": "m2", "user_id": "alice"})
    await store.create_node(["Memory"], {"id": "m3", "user_id": "bob"})
    await store.create_relationship("m1", "m2", "CAUSES")

    count = await store.delete_all_by_owner("alice")
    assert count >= 3  # 2 nodes + 1 relationship
    assert await store.get_node("m1") is None
    assert await store.get_node("m2") is None
    assert await store.get_node("m3") is not None  # bob's node survives


@pytest.mark.asyncio
async def test_delete_all_by_owner_custom_key(store: SQLiteGraphStore) -> None:
    await store.create_node(["Memory"], {"id": "m1", "tenant_id": "t1"})
    await store.create_node(["Memory"], {"id": "m2", "tenant_id": "t1"})
    await store.create_node(["Memory"], {"id": "m3", "tenant_id": "t2"})

    count = await store.delete_all_by_owner("t1", owner_key="tenant_id")
    assert count >= 2
    assert await store.get_node("m1") is None
    assert await store.get_node("m2") is None
    assert await store.get_node("m3") is not None


# ── Graph traversal ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_causal_chain(store: SQLiteGraphStore) -> None:
    for i in range(4):
        await store.create_node(["N"], {"id": f"n{i}"})
    await store.create_relationship("n0", "n1", "causes")
    await store.create_relationship("n1", "n2", "causes")
    await store.create_relationship("n2", "n3", "causes")

    chain = await store.get_causal_chain("n0", depth=5)
    assert chain == ["n1", "n2", "n3"]


@pytest.mark.asyncio
async def test_causal_chain_cycle_detection(store: SQLiteGraphStore) -> None:
    for i in range(3):
        await store.create_node(["N"], {"id": f"c{i}"})
    await store.create_relationship("c0", "c1", "causes")
    await store.create_relationship("c1", "c2", "causes")
    await store.create_relationship("c2", "c0", "causes")  # cycle

    chain = await store.get_causal_chain("c0", depth=10)
    assert "c0" not in chain  # should not revisit start
    assert len(chain) <= 3


@pytest.mark.asyncio
async def test_causal_chain_empty(store: SQLiteGraphStore) -> None:
    await store.create_node(["N"], {"id": "lonely"})
    chain = await store.get_causal_chain("lonely")
    assert chain == []


@pytest.mark.asyncio
async def test_get_related_nodes(store: SQLiteGraphStore) -> None:
    await store.create_node(["Memory"], {"id": "m1"})
    await store.create_node(["Memory"], {"id": "m2"})
    await store.create_node(["Entity"], {"id": "e1"})
    await store.create_relationship("m1", "e1", "MENTIONS")
    await store.create_relationship("m2", "e1", "MENTIONS")

    related = await store.get_related_nodes("m1", "MENTIONS")
    assert "m2" in related
    assert "m1" not in related


@pytest.mark.asyncio
async def test_get_related_nodes_with_depth(store: SQLiteGraphStore) -> None:
    # m1 --MENTIONS--> e1 <--MENTIONS-- m2 --MENTIONS--> e2 <--MENTIONS-- m3
    # m1 and m2 share e1 (depth 1), m1 and m3 share via m2 (depth 2)
    for nid in ("m1", "m2", "m3"):
        await store.create_node(["Memory"], {"id": nid})
    for eid in ("e1", "e2"):
        await store.create_node(["Entity"], {"id": eid})
    await store.create_relationship("m1", "e1", "MENTIONS")
    await store.create_relationship("m2", "e1", "MENTIONS")
    await store.create_relationship("m2", "e2", "MENTIONS")
    await store.create_relationship("m3", "e2", "MENTIONS")

    results = await store.get_related_nodes_with_depth("m1", "MENTIONS", max_depth=2)
    result_dict = dict(results)
    assert "m2" in result_dict
    assert result_dict["m2"] == 1
    # m3 is reachable at depth 2
    assert "m3" in result_dict


@pytest.mark.asyncio
async def test_get_related_nodes_with_depth_empty(store: SQLiteGraphStore) -> None:
    await store.create_node(["Memory"], {"id": "isolated"})
    results = await store.get_related_nodes_with_depth("isolated", "MENTIONS", max_depth=3)
    assert results == []


@pytest.mark.asyncio
async def test_update_node_properties_not_found(store: SQLiteGraphStore) -> None:
    result = await store.update_node_properties("nonexistent", {"key": "value"})
    assert result is None


@pytest.mark.asyncio
async def test_find_nodes_with_filter(store: SQLiteGraphStore) -> None:
    await store.create_node(["Claim"], {"id": "c1", "status": "active"})
    await store.create_node(["Claim"], {"id": "c2", "status": "resolved"})
    await store.create_node(["Claim"], {"id": "c3", "status": "active"})

    results = await store.find_nodes(["Claim"], {"status": "active"})
    result_ids = {n.id for n in results}
    assert result_ids == {"c1", "c3"}


@pytest.mark.asyncio
async def test_create_relationship_idempotent(store: SQLiteGraphStore) -> None:
    n1 = await store.create_node(["A"], {"id": "a1"})
    n2 = await store.create_node(["B"], {"id": "b1"})
    rel1 = await store.create_relationship(n1.id, n2.id, "LINKS")
    rel2 = await store.create_relationship(n1.id, n2.id, "LINKS")
    assert rel1.id == rel2.id


# ── Unsupported operations ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_execute_cypher_raises(store: SQLiteGraphStore) -> None:
    with pytest.raises(GraphNotSupportedError):
        await store.execute_cypher("MATCH (n) RETURN n")


# ── Lifecycle ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_health_check(store: SQLiteGraphStore) -> None:
    assert await store.health_check() is True


@pytest.mark.asyncio
async def test_context_manager(tmp_path: Path) -> None:
    async with SQLiteGraphStore(str(tmp_path / "ctx.db")) as s:
        node = await s.create_node(["T"], {"id": "t1"})
        assert node.id == "t1"


# ── Concurrency ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_concurrent_creates(store: SQLiteGraphStore) -> None:
    async def create(i: int) -> str:
        n = await store.create_node(["N"], {"id": f"cc_{i}"})
        return n.id

    ids = await asyncio.gather(*[create(i) for i in range(20)])
    assert len(set(ids)) == 20


# ── ORDER BY DESC + truncation ────────────────────────────────────────


@pytest.mark.asyncio
async def test_find_nodes_returns_newest_when_truncated(store: SQLiteGraphStore) -> None:
    """When limit < total nodes, find_nodes should return the most recently created nodes."""
    conn = await store._get_connection()
    for i in range(10):
        await conn.execute(
            "INSERT INTO graph_nodes (id, labels, properties, created_at) VALUES (?, ?, ?, ?)",
            (f"n{i:02d}", '["Claim"]', f'{{"id":"n{i:02d}","seq":{i}}}', f"2025-01-{i + 1:02d}T00:00:00"),
        )
    await conn.commit()

    results = await store.find_nodes(["Claim"], {}, limit=5)
    result_ids = [n.id for n in results]
    assert len(result_ids) == 5
    # DESC: should get n09, n08, n07, n06, n05 (newest first)
    assert result_ids == ["n09", "n08", "n07", "n06", "n05"]


@pytest.mark.asyncio
async def test_find_nodes_limit_greater_than_total(store: SQLiteGraphStore) -> None:
    """When limit > total, all nodes are returned."""
    for i in range(3):
        await store.create_node(["Tag"], {"id": f"t{i}"})

    results = await store.find_nodes(["Tag"], {}, limit=100)
    assert len(results) == 3


@pytest.mark.asyncio
async def test_find_nodes_labels_index_filters_correctly(store: SQLiteGraphStore) -> None:
    """Labels index should allow efficient filtering without scanning other label groups."""
    await store.create_node(["Claim"], {"id": "c1"})
    await store.create_node(["Entity"], {"id": "e1"})
    await store.create_node(["Memory"], {"id": "m1"})

    claims = await store.find_nodes(["Claim"], {})
    entities = await store.find_nodes(["Entity"], {})
    memories = await store.find_nodes(["Memory"], {})
    assert [n.id for n in claims] == ["c1"]
    assert [n.id for n in entities] == ["e1"]
    assert [n.id for n in memories] == ["m1"]


@pytest.mark.asyncio
async def test_find_nodes_filter_by_primary_namespace(store: SQLiteGraphStore) -> None:
    """find_nodes with primary_namespace filter should only return matching nodes."""
    await store.create_node(["Claim"], {"primary_namespace": "agent:alice", "claim_text": "a"})
    await store.create_node(["Claim"], {"primary_namespace": "agent:bob", "claim_text": "b"})
    await store.create_node(["Claim"], {"primary_namespace": "agent:alice", "claim_text": "c"})

    alice_claims = await store.find_nodes(["Claim"], {"primary_namespace": "agent:alice"})
    bob_claims = await store.find_nodes(["Claim"], {"primary_namespace": "agent:bob"})
    all_claims = await store.find_nodes(["Claim"], {})

    assert len(alice_claims) == 2
    assert len(bob_claims) == 1
    assert len(all_claims) == 3
    assert all(n.properties.get("primary_namespace") == "agent:alice" for n in alice_claims)
    assert bob_claims[0].properties.get("primary_namespace") == "agent:bob"


# ── Causal chain & pushdown filters ───────────────────────────────────


@pytest.mark.asyncio
async def test_get_causal_chain_traversal_and_substring_safety(store: SQLiteGraphStore) -> None:
    """Empty relation_types should traverse all, and node_2 shouldn't falsely cycle with node_20."""
    n_root = await store.create_node(["Claim"], {"id": "node_root"})
    n_20 = await store.create_node(["Claim"], {"id": "node_20"})
    n_2 = await store.create_node(["Claim"], {"id": "node_2"})
    n_leaf = await store.create_node(["Claim"], {"id": "node_leaf"})

    await store.create_relationship(n_root.id, n_20.id, "causes")
    await store.create_relationship(n_20.id, n_2.id, "causes")
    await store.create_relationship(n_2.id, n_leaf.id, "causes")

    # 1. Empty relation_types should traverse without SQL syntax error
    chain_all = await store.get_causal_chain(n_root.id, depth=5, relation_types=[])
    assert set(chain_all) == {n_20.id, n_2.id, n_leaf.id}

    # 2. Filtered relation_types should traverse
    chain_causes = await store.get_causal_chain(n_root.id, depth=5, relation_types=["causes"])
    assert set(chain_causes) == {n_20.id, n_2.id, n_leaf.id}


@pytest.mark.asyncio
async def test_list_nodes_with_namespace_pushdown(store: SQLiteGraphStore) -> None:
    """list_nodes with namespace should filter on primary_namespace expression index."""
    await store.create_node(["Claim"], {"id": "a1", "primary_namespace": "agent_alpha"})
    await store.create_node(["Claim"], {"id": "a2", "primary_namespace": "agent_alpha"})
    await store.create_node(["Claim"], {"id": "b1", "primary_namespace": "agent_beta"})

    alpha_nodes = await store.list_nodes(namespace="agent_alpha")
    beta_nodes = await store.list_nodes(namespace="agent_beta")
    all_nodes = await store.list_nodes()

    assert {n.id for n in alpha_nodes} == {"a1", "a2"}
    assert {n.id for n in beta_nodes} == {"b1"}
    assert len(all_nodes) >= 3


@pytest.mark.asyncio
async def test_list_relationships_induced_subgraph_pushdown(store: SQLiteGraphStore) -> None:
    """list_relationships with node_ids should fetch exact induced subgraph."""
    n1 = await store.create_node(["Claim"], {"id": "n1"})
    n2 = await store.create_node(["Claim"], {"id": "n2"})
    n3 = await store.create_node(["Claim"], {"id": "n3"})

    r12 = await store.create_relationship(n1.id, n2.id, "SUPPORTS")
    r23 = await store.create_relationship(n2.id, n3.id, "CONTRADICTS")

    # Subgraph of {n1, n2} should only return r12
    subgraph_12 = await store.list_relationships(node_ids=[n1.id, n2.id])
    assert len(subgraph_12) == 1
    assert subgraph_12[0].id == r12.id

    # Empty list should short-circuit to empty
    assert await store.list_relationships(node_ids=[]) == []

    # Unfiltered should return all
    all_rels = await store.list_relationships()
    rel_ids = {r.id for r in all_rels}
    assert r12.id in rel_ids and r23.id in rel_ids


@pytest.mark.asyncio
async def test_get_stats_aggregates_labels_and_rel_types(store: SQLiteGraphStore) -> None:
    """get_stats should correctly aggregate nodes, relationships, labels, and types."""
    n1 = await store.create_node(["Claim", "Memory"], {"id": "stat_1"})
    n2 = await store.create_node(["Claim"], {"id": "stat_2"})
    await store.create_relationship(n1.id, n2.id, "SUPPORTS")

    stats = await store.get_stats()
    assert stats.node_count >= 2
    assert stats.relationship_count >= 1
    assert stats.node_label_counts.get("Claim", 0) >= 2
    assert stats.node_label_counts.get("Memory", 0) >= 1
    assert stats.relationship_type_counts.get("SUPPORTS", 0) >= 1


# ── Exception branch coverage tests ───────────────────────────────────


@pytest.mark.asyncio
async def test_connection_error_raises_graph_connection_error(tmp_path: Path) -> None:
    store = SQLiteGraphStore(str(tmp_path / "valid.db"))
    store._db_path = Path("/dev/null/not_a_dir/test.db")
    with pytest.raises(GraphConnectionError):
        await store.create_node(["Claim"], {})


@pytest.mark.asyncio
async def test_create_node_unserializable_raises_graph_query_error(store: SQLiteGraphStore) -> None:
    with pytest.raises(GraphQueryError):
        # Pass non-serializable object to trigger GraphQueryError
        await store.create_node(["Claim"], {"invalid": object()})  # type: ignore[dict-item]


@pytest.mark.asyncio
async def test_create_relationship_unserializable_raises_graph_query_error(store: SQLiteGraphStore) -> None:
    with pytest.raises(GraphQueryError):
        await store.create_relationship("a", "b", "REL", {"invalid": object()})  # type: ignore[dict-item]


@pytest.mark.asyncio
async def test_update_properties_unserializable_raises_graph_query_error(store: SQLiteGraphStore) -> None:
    n = await store.create_node(["Claim"], {"id": "up_err_1"})
    with pytest.raises(GraphQueryError):
        await store.update_node_properties(n.id, {"invalid": object()})  # type: ignore[dict-item]


@pytest.mark.asyncio
async def test_delete_all_by_owner_nonexistent_returns_zero(store: SQLiteGraphStore) -> None:
    assert await store.delete_all_by_owner("nonexistent_owner") == 0


@pytest.mark.asyncio
async def test_list_nodes_and_relationships_pagination(store: SQLiteGraphStore) -> None:
    for i in range(5):
        await store.create_node(["Claim"], {"id": f"pg_n{i}"})
    for i in range(4):
        await store.create_relationship(f"pg_n{i}", f"pg_n{i+1}", "LINK")

    nodes_page = await store.list_nodes(limit=2, offset=1)
    assert len(nodes_page) == 2

    rels_page = await store.list_relationships(limit=2, offset=1)
    assert len(rels_page) == 2
