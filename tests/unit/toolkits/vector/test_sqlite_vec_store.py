"""Unit tests for SQLite-vec embedded vector store and temporal decay scoring.

[POS]
Unit test suite verifying SqliteVecStore CRUD, cosine similarity,
dual-track fallback, temporal decay reranking, and persistent durability.

[INPUT]
- pytest, tempfile, datetime
- myrm_agent_harness.toolkits.vector (VectorDocument, SearchResult)
- myrm_agent_harness.toolkits.vector.sqlite_vec (
    SqliteVecConfig,
    SqliteVecStore,
    TemporalDecayScorer,
    SqliteVecEngineMode,
  )

[OUTPUT]
- Test functions covering vector store capabilities.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.vector.base import VectorDocument
from myrm_agent_harness.toolkits.vector.sqlite_vec import (
    SqliteVecConfig,
    SqliteVecStore,
    TemporalDecayScorer,
)


@pytest.fixture
def temp_db_path(tmp_path: Path) -> Path:
    """Fixture providing temporary sqlite database path."""
    return tmp_path / "test_vector.db"


def test_temporal_decay_scorer_math() -> None:
    """Verify temporal decay exponential half-life mathematics and resistance."""
    scorer = TemporalDecayScorer(default_half_life_seconds=86400.0, floor_score=0.2)
    now = datetime(2026, 10, 7, 12, 0, 0, tzinfo=UTC)

    # 1. Zero delta: decay factor should be 1.0
    factor_fresh = scorer.compute_decay_factor(created_at=now, now=now)
    assert pytest.approx(factor_fresh, rel=1e-3) == 1.0

    # 2. Exactly one half-life (1 day ago): raw_decay = 0.5 -> floor + 0.8 * 0.5 = 0.6
    one_day_ago = now - timedelta(days=1)
    factor_1d = scorer.compute_decay_factor(created_at=one_day_ago, now=now)
    assert pytest.approx(factor_1d, rel=1e-3) == 0.6

    # 3. High importance weight (importance=3.0) resists decay
    factor_important = scorer.compute_decay_factor(
        created_at=one_day_ago, importance_weight=3.0, now=now
    )
    assert factor_important > factor_1d

    # 4. Long time ago (100 days): factor should never drop below floor_score (0.2)
    ancient = now - timedelta(days=100)
    factor_ancient = scorer.compute_decay_factor(created_at=ancient, now=now)
    assert factor_ancient >= 0.2


@pytest.mark.asyncio
async def test_sqlite_vec_store_lifecycle_and_crud(temp_db_path: Path) -> None:
    """Verify initialization, collection creation, upsert, get, delete, scroll, and count."""
    config = SqliteVecConfig(db_path=str(temp_db_path))
    store = SqliteVecStore(config)

    assert store.is_persistent is True
    assert await store.health_check() is True

    coll = "test_memory"
    await store.ensure_collection(coll, dimension=3)
    assert await store.collection_exists(coll) is True

    # Initial count
    assert await store.count(coll) == 0

    # Upsert documents
    doc1 = VectorDocument(
        id="doc_1",
        content="Alpha memory norm",
        vector=[1.0, 0.0, 0.0],
        metadata={"category": "rule", "importance_weight": 2.0},
    )
    doc2 = VectorDocument(
        id="doc_2",
        content="Beta temporary note",
        vector=[0.0, 1.0, 0.0],
        metadata={"category": "scratch"},
    )
    doc3 = VectorDocument(
        id="doc_3",
        content="Gamma rule variant",
        vector=[0.707, 0.707, 0.0],
        metadata={"category": "rule"},
    )

    upserted = await store.upsert(coll, [doc1, doc2, doc3])
    assert upserted == ["doc_1", "doc_2", "doc_3"]
    assert await store.count(coll) == 3

    # Get by ID
    fetched = await store.get(coll, ["doc_1", "doc_2"])
    assert len(fetched) == 2
    ids = {d.id for d in fetched}
    assert ids == {"doc_1", "doc_2"}

    # Scroll with limit
    scrolled_docs, next_offset = await store.scroll(coll, limit=2)
    assert len(scrolled_docs) == 2
    assert next_offset is not None

    # Filter scroll
    rule_docs, _ = await store.scroll(coll, filters={"category": "rule"})
    assert len(rule_docs) == 2

    # Delete single doc
    deleted_count = await store.delete(coll, ["doc_2"])
    assert deleted_count == 1
    assert await store.count(coll) == 2

    # Delete by filter
    del_filter_count = await store.delete_by_filter(coll, filters={"category": "rule"})
    assert del_filter_count == 2
    assert await store.count(coll) == 0

    await store.close()


@pytest.mark.asyncio
async def test_sqlite_vec_search_and_temporal_decay(temp_db_path: Path) -> None:
    """Verify similarity search and time-decayed ranking."""
    config = SqliteVecConfig(db_path=str(temp_db_path), default_half_life_seconds=86400.0)
    store = SqliteVecStore(config)
    coll = "search_test"
    await store.ensure_collection(coll, dimension=2)

    now = datetime.now(UTC)
    doc_fresh = VectorDocument(
        id="fresh_rule",
        content="Newly adopted coding rule",
        vector=[1.0, 0.0],
        metadata={"importance_weight": 1.0},
        created_at=now,
    )
    doc_old = VectorDocument(
        id="old_rule",
        content="Old deprecated coding rule",
        vector=[1.0, 0.0],  # Same vector similarity!
        metadata={"importance_weight": 1.0},
        created_at=now - timedelta(days=3),  # 3 half-lives ago
    )

    await store.upsert(coll, [doc_fresh, doc_old])

    # 1. Raw search: identical vectors yield identical raw cosine scores
    raw_results = await store.search(coll, query_vector=[1.0, 0.0], limit=2)
    assert len(raw_results) == 2
    assert pytest.approx(raw_results[0].score, rel=1e-3) == raw_results[1].score

    # 2. Decayed search: fresh_rule must be ranked significantly higher than old_rule
    decayed_results = await store.search_decayed(coll, query_vector=[1.0, 0.0], limit=2)
    assert len(decayed_results) == 2
    assert decayed_results[0].document.id == "fresh_rule"
    assert decayed_results[1].document.id == "old_rule"
    assert decayed_results[0].decayed_score > decayed_results[1].decayed_score

    await store.close()


@pytest.mark.asyncio
async def test_sqlite_vec_persistence_durability(temp_db_path: Path) -> None:
    """Verify data durability across separate store instance lifecycles."""
    config = SqliteVecConfig(db_path=str(temp_db_path))

    # Instance 1: write data and close
    store1 = SqliteVecStore(config)
    coll = "persistent_coll"
    await store1.ensure_collection(coll, dimension=2)
    await store1.upsert(
        coll,
        [VectorDocument(id="p1", content="durable text", vector=[0.5, 0.5])],
    )
    await store1.close()

    # Instance 2: reopen same file path and retrieve
    store2 = SqliteVecStore(config)
    assert await store2.collection_exists(coll) is True
    assert await store2.count(coll) == 1

    docs = await store2.get(coll, ["p1"])
    assert len(docs) == 1
    assert docs[0].content == "durable text"
    assert docs[0].vector is not None
    assert pytest.approx(docs[0].vector[0], rel=1e-3) == 0.5

    await store2.close()
