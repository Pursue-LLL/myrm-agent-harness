"""Tests for SQLite bi-temporal knowledge graph query and lifecycle."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.memory.governance.graph_bridge import EntityGraphBridge
from myrm_agent_harness.toolkits.memory.graph.exceptions import GraphQueryError
from myrm_agent_harness.toolkits.memory.graph.sqlite_store import SQLiteGraphStore


@pytest.fixture
async def store(tmp_path: Path) -> SQLiteGraphStore:
    s = SQLiteGraphStore(str(tmp_path / "test_temporal.db"))
    yield s  # type: ignore[misc]
    await s.close()


@pytest.mark.asyncio
async def test_temporal_columns_and_partial_unique_index_created(
    store: SQLiteGraphStore,
) -> None:
    conn = await store._get_connection()
    async with conn.execute("PRAGMA table_info(graph_relationships)") as cursor:
        cols = {row[1]: row[2] for row in await cursor.fetchall()}

    for expected_col in ["valid_from", "valid_until", "superseded_by", "supersedes_id"]:
        assert expected_col in cols

    async with conn.execute("PRAGMA index_list(graph_relationships)") as cursor:
        indexes = {row[1]: row[2] for row in await cursor.fetchall()}

    assert "idx_graph_rel_unique" in indexes
    assert "idx_graph_rel_valid_window" in indexes


@pytest.mark.asyncio
async def test_create_relationship_sets_temporal_defaults(
    store: SQLiteGraphStore,
) -> None:
    await store.create_node(labels=["Person"], properties={"id": "alice", "name": "Alice"})
    await store.create_node(labels=["Team"], properties={"id": "alpha", "name": "Alpha"})

    rel = await store.create_relationship(
        start_id="alice",
        end_id="alpha",
        rel_type="MEMBER_OF",
        properties={"role": "engineer"},
    )

    assert rel.valid_from is not None
    datetime.fromisoformat(rel.valid_from.replace("Z", "+00:00"))
    assert rel.valid_until is None
    assert rel.superseded_by is None
    assert rel.supersedes_id is None


@pytest.mark.asyncio
async def test_supersede_relationship_lifecycle(store: SQLiteGraphStore) -> None:
    await store.create_node(labels=["Person"], properties={"id": "bob", "name": "Bob"})
    await store.create_node(labels=["Org"], properties={"id": "corp", "name": "Corp"})

    r1 = await store.create_relationship(
        start_id="bob",
        end_id="corp",
        rel_type="WORKS_AT",
        properties={"role": "intern"},
    )

    await asyncio.sleep(0.01)

    old_closed, r2 = await store.supersede_relationship(
        old_rel_id=r1.id,
        new_properties={"role": "staff_engineer"},
    )

    assert old_closed.id == r1.id
    assert old_closed.valid_until is not None
    assert old_closed.superseded_by == r2.id

    assert r2.id != r1.id
    assert r2.start_id == "bob"
    assert r2.end_id == "corp"
    assert r2.rel_type == "WORKS_AT"
    assert r2.properties == {"role": "staff_engineer"}
    assert r2.supersedes_id == r1.id
    assert r2.valid_until is None

    conn = await store._get_connection()
    async with conn.execute(
        "SELECT valid_until, superseded_by FROM graph_relationships WHERE id = ?",
        (r1.id,),
    ) as cur:
        row = await cur.fetchone()
        assert row is not None
        assert row[0] is not None
        assert row[1] == r2.id


@pytest.mark.asyncio
async def test_supersede_nonexistent_raises_graph_query_error(
    store: SQLiteGraphStore,
) -> None:
    with pytest.raises(GraphQueryError, match="not found"):
        await store.supersede_relationship(
            old_rel_id="nonexistent-id",
            new_properties={"role": "ghost"},
        )


@pytest.mark.asyncio
async def test_supersede_preceding_valid_from_raises_error(store: SQLiteGraphStore) -> None:
    await store.create_node(labels=["A"], properties={"id": "node_a"})
    await store.create_node(labels=["B"], properties={"id": "node_b"})
    rel = await store.create_relationship(
        start_id="node_a",
        end_id="node_b",
        rel_type="CONNECTS",
        valid_from="2026-09-18T10:00:00Z",
    )
    with pytest.raises(GraphQueryError, match="cannot precede original valid_from"):
        await store.supersede_relationship(
            old_rel_id=rel.id,
            as_of_time="2026-09-18T09:00:00Z",
            new_properties={"state": "future"},
        )


@pytest.mark.asyncio
async def test_partial_unique_index_allows_superseded_duplicates(
    store: SQLiteGraphStore,
) -> None:
    await store.create_node(labels=["A"], properties={"id": "a1"})
    await store.create_node(labels=["B"], properties={"id": "b1"})

    r1 = await store.create_relationship(start_id="a1", end_id="b1", rel_type="LINK", properties={"v": 1})
    _, r2 = await store.supersede_relationship(r1.id, new_properties={"v": 2})

    # create_relationship with same (start_id, end_id, rel_type) returns active r2
    r_existing = await store.create_relationship(start_id="a1", end_id="b1", rel_type="LINK", properties={"v": 2})
    assert r_existing.id == r2.id

    all_rels = await store.list_relationships(include_superseded=True)
    assert len(all_rels) == 2


@pytest.mark.asyncio
async def test_list_relationships_as_of_time_travel(store: SQLiteGraphStore) -> None:
    await store.create_node(labels=["User"], properties={"id": "user1"})
    await store.create_node(labels=["Project"], properties={"id": "proj1"})

    t_before = datetime.now(UTC).isoformat()
    await asyncio.sleep(0.02)

    r1 = await store.create_relationship(
        start_id="user1", end_id="proj1", rel_type="CONTRIBUTES_TO", properties={"tier": "bronze"}
    )
    await asyncio.sleep(0.02)

    t_between = datetime.now(UTC).isoformat()
    await asyncio.sleep(0.02)

    _, r2 = await store.supersede_relationship(r1.id, new_properties={"tier": "gold"})
    await asyncio.sleep(0.02)

    t_after = datetime.now(UTC).isoformat()

    # Query before r1 was created
    past_rels = await store.list_relationships(as_of_time=t_before)
    assert len(past_rels) == 0

    # Query during r1's active time
    mid_rels = await store.list_relationships(as_of_time=t_between)
    assert len(mid_rels) == 1
    assert mid_rels[0].id == r1.id
    assert mid_rels[0].properties.get("tier") == "bronze"

    # Query after r2 superseded r1
    now_rels = await store.list_relationships(as_of_time=t_after)
    assert len(now_rels) == 1
    assert now_rels[0].id == r2.id
    assert now_rels[0].properties.get("tier") == "gold"

    # Default query returns active relationship
    active_rels = await store.list_relationships()
    assert len(active_rels) == 1
    assert active_rels[0].id == r2.id

    # Query all versions
    all_versions = await store.list_relationships(include_superseded=True)
    assert len(all_versions) == 2


@pytest.mark.asyncio
async def test_causal_chain_ignores_superseded_edges(store: SQLiteGraphStore) -> None:
    await store.create_node(labels=["Node"], properties={"id": "c1"})
    await store.create_node(labels=["Node"], properties={"id": "c2"})
    await store.create_node(labels=["Node"], properties={"id": "c3"})

    r12 = await store.create_relationship(start_id="c1", end_id="c2", rel_type="causes")
    await store.create_relationship(start_id="c2", end_id="c3", rel_type="causes")

    chain_ids = await store.get_causal_chain("c1", depth=5)
    assert chain_ids == ["c2", "c3"]

    # Mark r12 as superseded/expired
    conn = await store._get_connection()
    await conn.execute(
        "UPDATE graph_relationships SET valid_until = '2000-01-01T00:00:00Z' WHERE id = ?",
        (r12.id,),
    )
    await conn.commit()

    # Now the forward chain from c1 should be empty because outgoing edge r12 is expired
    broken_chain = await store.get_causal_chain("c1", depth=5)
    assert broken_chain == []


@pytest.mark.asyncio
async def test_get_related_nodes_ignores_superseded_edges(store: SQLiteGraphStore) -> None:
    await store.create_node(labels=["Entity"], properties={"id": "e1"})
    await store.create_node(labels=["Entity"], properties={"id": "e2"})
    await store.create_node(labels=["Topic"], properties={"id": "topic1"})

    # e1 -> topic1, e2 -> topic1
    r1 = await store.create_relationship(start_id="e1", end_id="topic1", rel_type="MENTIONS")
    await store.create_relationship(start_id="e2", end_id="topic1", rel_type="MENTIONS")

    related = await store.get_related_nodes("e1", rel_type="MENTIONS")
    assert "e2" in related

    conn = await store._get_connection()
    await conn.execute(
        "UPDATE graph_relationships SET valid_until = '2000-01-01T00:00:00Z' WHERE id = ?",
        (r1.id,),
    )
    await conn.commit()

    active_related = await store.get_related_nodes("e1", rel_type="MENTIONS")
    assert len(active_related) == 0


@pytest.mark.asyncio
async def test_entity_graph_bridge_with_as_of_time(store: SQLiteGraphStore) -> None:
    await store.create_node(labels=["User"], properties={"id": "dev1", "name": "Dev"})
    await store.create_node(labels=["Repo"], properties={"id": "repo1", "name": "Repo"})

    r1 = await store.create_relationship(start_id="dev1", end_id="repo1", rel_type="MAINTAINS")
    await asyncio.sleep(0.02)
    t_v1 = datetime.now(UTC).isoformat()
    await asyncio.sleep(0.02)

    await store.supersede_relationship(old_rel_id=r1.id, new_rel_type="LEADS")
    await asyncio.sleep(0.02)
    t_v2 = datetime.now(UTC).isoformat()

    bridge = EntityGraphBridge(graph_store=store)

    text_v1 = await bridge.get_bounded_subgraph_text(["Dev"], as_of_time=t_v1)
    assert "MAINTAINS" in text_v1
    assert "LEADS" not in text_v1

    text_v2 = await bridge.get_bounded_subgraph_text(["Dev"], as_of_time=t_v2)
    assert "LEADS" in text_v2
    assert "MAINTAINS" not in text_v2
