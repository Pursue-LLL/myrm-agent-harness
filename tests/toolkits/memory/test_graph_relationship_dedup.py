"""Unit tests for graph relationship deduplication (idempotent create_relationship).

Validates that SQLiteGraphStore's create_relationship is idempotent:
- Duplicate (source, target, type) calls return existing relationship
- Different rel_type allows multiple relationships between same nodes
- UNIQUE INDEX prevents data corruption at DB level
"""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.memory.graph.sqlite_store import SQLiteGraphStore


@pytest.fixture()
def db_path(tmp_path: Path) -> str:
    return str(tmp_path / "test_graph.db")


@pytest.fixture()
def store(db_path: str) -> SQLiteGraphStore:
    return SQLiteGraphStore(db_path)


@pytest.mark.asyncio()
async def test_create_relationship_idempotent(store: SQLiteGraphStore) -> None:
    """Same (source, target, rel_type) should not create duplicate relationships."""
    async with store:
        node_a = await store.create_node(["Memory"], {"id": "a"})
        node_b = await store.create_node(["Entity"], {"id": "b", "name": "test"})

        rel1 = await store.create_relationship(node_a.id, node_b.id, "MENTIONS")
        rel2 = await store.create_relationship(node_a.id, node_b.id, "MENTIONS")

        assert rel1.id == rel2.id
        assert rel1.start_id == rel2.start_id
        assert rel1.end_id == rel2.end_id
        assert rel1.rel_type == rel2.rel_type


@pytest.mark.asyncio()
async def test_different_rel_type_creates_separate_relationships(store: SQLiteGraphStore) -> None:
    """Different rel_type between same nodes should create separate relationships."""
    async with store:
        node_a = await store.create_node(["Memory"], {"id": "a"})
        node_b = await store.create_node(["Entity"], {"id": "b", "name": "test"})

        rel_mentions = await store.create_relationship(node_a.id, node_b.id, "MENTIONS")
        rel_causes = await store.create_relationship(node_a.id, node_b.id, "CAUSES")

        assert rel_mentions.id != rel_causes.id
        assert rel_mentions.rel_type == "MENTIONS"
        assert rel_causes.rel_type == "CAUSES"


@pytest.mark.asyncio()
async def test_many_duplicate_calls_no_accumulation(store: SQLiteGraphStore) -> None:
    """10 duplicate calls should result in exactly 1 relationship."""
    async with store:
        node_a = await store.create_node(["Memory"], {"id": "a"})
        node_b = await store.create_node(["Entity"], {"id": "b", "name": "test"})

        ids = set()
        for _ in range(10):
            rel = await store.create_relationship(node_a.id, node_b.id, "MENTIONS")
            ids.add(rel.id)

        assert len(ids) == 1

        conn = await store._get_connection()
        async with conn.execute(
            "SELECT COUNT(*) FROM graph_relationships WHERE source_id = ? AND target_id = ? AND rel_type = ?",
            (node_a.id, node_b.id, "MENTIONS"),
        ) as cursor:
            count = (await cursor.fetchone())[0]
        assert count == 1


@pytest.mark.asyncio()
async def test_unique_index_exists(store: SQLiteGraphStore) -> None:
    """Verify the UNIQUE INDEX is created on initialization."""
    async with store:
        conn = await store._get_connection()
        async with conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_graph_rel_unique'"
        ) as cursor:
            row = await cursor.fetchone()
        assert row is not None, "UNIQUE index idx_graph_rel_unique should exist"


@pytest.mark.asyncio()
async def test_idempotent_returns_correct_properties(store: SQLiteGraphStore) -> None:
    """Existing relationship should return its original properties."""
    async with store:
        node_a = await store.create_node(["Claim"], {"id": "claim_1"})
        node_b = await store.create_node(["Evidence"], {"id": "ev_1"})

        props = {"confidence": 0.95, "freshness_days": 3.0}
        rel1 = await store.create_relationship(node_a.id, node_b.id, "SUPPORTED_BY", props)
        rel2 = await store.create_relationship(node_a.id, node_b.id, "SUPPORTED_BY")

        assert rel2.id == rel1.id
        assert rel2.properties["confidence"] == 0.95


@pytest.mark.asyncio()
async def test_reverse_direction_is_different(store: SQLiteGraphStore) -> None:
    """A->B and B->A should be treated as different relationships."""
    async with store:
        node_a = await store.create_node(["Node"], {"id": "a"})
        node_b = await store.create_node(["Node"], {"id": "b"})

        rel_ab = await store.create_relationship(node_a.id, node_b.id, "MENTIONS")
        rel_ba = await store.create_relationship(node_b.id, node_a.id, "MENTIONS")

        assert rel_ab.id != rel_ba.id


@pytest.mark.asyncio()
async def test_causal_chain_no_path_explosion(store: SQLiteGraphStore) -> None:
    """With dedup, causal chain traversal should not suffer from duplicate edges."""
    async with store:
        nodes = []
        for i in range(5):
            n = await store.create_node(["Step"], {"id": f"step_{i}"})
            nodes.append(n)

        for i in range(4):
            for _ in range(5):
                await store.create_relationship(nodes[i].id, nodes[i + 1].id, "causes")

        chain = await store.get_causal_chain(nodes[0].id, depth=10, relation_types=["causes"])
        assert len(chain) == 4
        assert chain == [n.id for n in nodes[1:]]
