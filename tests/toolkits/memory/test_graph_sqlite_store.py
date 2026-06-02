"""SQLiteGraphStore unit tests — CRUD, traversal, lifecycle, edge cases."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.memory.graph import SQLiteGraphStore
from myrm_agent_harness.toolkits.memory.graph.exceptions import GraphNotSupportedError
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
