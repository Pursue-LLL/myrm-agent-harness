"""[POS]: tests/unit/toolkits/memory/test_temporal_graph_suite.py
[INPUT]: SqliteTemporalGraphStore, TemporalDecayScorer, TemporalFactConflictReconciler, and models.
[OUTPUT]: Unit tests verifying temporal entity nodes, half-life decay scoring, and fact conflict reconciliation.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.memory.temporal_graph import (
    SqliteTemporalGraphStore,
    TemporalDecayScorer,
    TemporalEntityNode,
    TemporalFactConflictReconciler,
    TemporalFactEdge,
)


@pytest.fixture
def isolated_store(tmp_path: Path) -> SqliteTemporalGraphStore:
    """Provides an isolated SQLite store for temporal graph."""
    db_file = tmp_path / "test_temporal_graph.db"
    return SqliteTemporalGraphStore(db_path=db_file)


def test_entity_node_crud_and_lookup(isolated_store: SqliteTemporalGraphStore) -> None:
    """Verifies creating, retrieving, querying, and deleting entity nodes."""
    node1 = TemporalEntityNode(
        node_id="ent_user_01",
        name="Alice",
        entity_type="user",
        attributes={"department": "Engineering"},
    )
    isolated_store.save_node(node1)

    node2 = TemporalEntityNode(
        node_id="ent_comp_01",
        name="Acme Corp",
        entity_type="organization",
        attributes={"industry": "AI"},
    )
    isolated_store.save_node(node2)

    # Lookup by ID
    retrieved = isolated_store.get_node("ent_user_01")
    assert retrieved is not None
    assert retrieved.name == "Alice"
    assert retrieved.attributes["department"] == "Engineering"

    # Find by name
    found = isolated_store.find_node("Acme Corp", entity_type="organization")
    assert found is not None
    assert found.node_id == "ent_comp_01"

    # List nodes
    all_nodes = isolated_store.list_nodes()
    assert len(all_nodes) == 2

    # Delete node
    assert isolated_store.delete_node("ent_comp_01") is True
    assert isolated_store.get_node("ent_comp_01") is None


def test_temporal_decay_scorer_and_access_reinforcement() -> None:
    """Verifies exponential half-life decay calculation, supersession penalty, and access boost."""
    scorer = TemporalDecayScorer(half_life_days=30.0, superseded_penalty=0.05)
    now = datetime.now(UTC)

    # 1. Fresh edge as of today
    fresh_edge = TemporalFactEdge(
        edge_id="edge_fresh",
        source_id="user_1",
        target_id="city_1",
        predicate="residence_city",
        valid_from=now,
        confidence_score=1.0,
    )
    score_fresh, status_fresh = scorer.calculate_score(fresh_edge, as_of=now)
    assert status_fresh == "active"
    assert 0.99 <= score_fresh <= 1.0

    # 2. 30 days old edge (1 half-life elapsed)
    thirty_days_ago = now - timedelta(days=30)
    aged_edge = TemporalFactEdge(
        edge_id="edge_aged",
        source_id="user_1",
        target_id="city_1",
        predicate="residence_city",
        valid_from=thirty_days_ago,
        confidence_score=1.0,
    )
    score_aged, status_aged = scorer.calculate_score(aged_edge, as_of=now)
    assert status_aged == "active"
    assert 0.49 <= score_aged <= 0.51

    # 3. Superseded edge receives severe penalty
    superseded_edge = TemporalFactEdge(
        edge_id="edge_old",
        source_id="user_1",
        target_id="city_old",
        predicate="residence_city",
        valid_from=now,
        is_superseded=True,
        superseded_by="edge_fresh",
        confidence_score=1.0,
    )
    score_super, status_super = scorer.calculate_score(superseded_edge, as_of=now)
    assert status_super == "superseded"
    assert score_super == 0.05

    # 4. Access reinforcement bonus
    scorer.record_access(fresh_edge, access_time=now)
    assert fresh_edge.access_count == 1
    assert fresh_edge.last_accessed_at == now


def test_fact_conflict_reconciler_and_supersession_lineage(
    isolated_store: SqliteTemporalGraphStore,
) -> None:
    """Verifies that mutually exclusive predicates supersede historical edges and build evolutionary lineage."""
    reconciler = TemporalFactConflictReconciler()
    t0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
    t1 = datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC)
    t2 = datetime(2026, 10, 1, 0, 0, 0, tzinfo=UTC)

    user_id = "user_dev_01"

    # Edge 1: User works_at StartupA in January 2026
    edge1 = TemporalFactEdge(
        edge_id="edge_work_01",
        source_id=user_id,
        target_id="company_startup_a",
        predicate="works_at",
        valid_from=t0,
    )
    res1 = reconciler.resolve_and_insert(isolated_store, edge1)
    assert res1.is_conflict_detected is False
    assert len(res1.superseded_edges) == 0

    # Edge 2: User changes job to TechCorp in June 2026
    edge2 = TemporalFactEdge(
        edge_id="edge_work_02",
        source_id=user_id,
        target_id="company_techcorp_b",
        predicate="works_at",
        valid_from=t1,
    )
    res2 = reconciler.resolve_and_insert(isolated_store, edge2)
    assert res2.is_conflict_detected is True
    assert len(res2.superseded_edges) == 1
    assert res2.superseded_edges[0].edge_id == "edge_work_01"

    # Verify edge1 was marked superseded in store
    saved_edge1 = isolated_store.get_edge("edge_work_01")
    assert saved_edge1 is not None
    assert saved_edge1.is_superseded is True
    assert saved_edge1.superseded_by == "edge_work_02"
    assert saved_edge1.valid_until == t1

    # Edge 3: User founded AIStudio in October 2026
    edge3 = TemporalFactEdge(
        edge_id="edge_work_03",
        source_id=user_id,
        target_id="company_aistudio_c",
        predicate="works_at",
        valid_from=t2,
    )
    res3 = reconciler.resolve_and_insert(isolated_store, edge3)
    assert res3.is_conflict_detected is True
    assert len(res3.superseded_edges) == 1
    assert res3.superseded_edges[0].edge_id == "edge_work_02"

    # Trace backward lineage: edge3 -> edge2 -> edge1
    lineage = reconciler.get_supersession_lineage(isolated_store, "edge_work_03")
    assert len(lineage) == 3
    assert [e.edge_id for e in lineage] == ["edge_work_03", "edge_work_02", "edge_work_01"]
