"""[POS]: tests/unit/toolkits/memory/test_temporal_knowledge_graph_suite.py
[INPUT]: Temporary SQLite storage, temporal graph store, conflict reconciler, and decay scorer.
[OUTPUT]: Unit tests verifying temporal node/edge CRUD, mutual exclusion conflict supersession, and decay scoring.
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
def temp_store(tmp_path: Path) -> SqliteTemporalGraphStore:
    """Fixture providing an isolated temporal graph SQLite store."""
    db_file = tmp_path / "test_temporal_graph.db"
    return SqliteTemporalGraphStore(db_path=db_file)


def test_temporal_node_and_edge_crud(temp_store: SqliteTemporalGraphStore) -> None:
    """Verifies basic entity node and fact edge persistence and retrieval."""
    now = datetime.now(UTC)
    node_user = TemporalEntityNode(
        node_id="node_user_01",
        name="Alice",
        entity_type="user",
        attributes={"department": "Platform Engineering"},
        created_at=now,
        updated_at=now,
    )
    node_comp = TemporalEntityNode(
        node_id="node_comp_01",
        name="Acme Corp",
        entity_type="organization",
        attributes={"industry": "AI Infrastructure"},
        created_at=now,
        updated_at=now,
    )

    temp_store.save_node(node_user)
    temp_store.save_node(node_comp)

    # 1. Node lookups
    retrieved_user = temp_store.get_node("node_user_01")
    assert retrieved_user is not None
    assert retrieved_user.name == "Alice"
    assert retrieved_user.attributes["department"] == "Platform Engineering"

    found_comp = temp_store.find_node("Acme Corp", entity_type="organization")
    assert found_comp is not None
    assert found_comp.node_id == "node_comp_01"

    # 2. Edge persistence
    edge = TemporalFactEdge(
        edge_id="edge_001",
        source_id="node_user_01",
        target_id="node_comp_01",
        predicate="works_at",
        valid_from=now,
        confidence_score=1.0,
    )
    temp_store.save_edge(edge)

    retrieved_edge = temp_store.get_edge("edge_001")
    assert retrieved_edge is not None
    assert retrieved_edge.predicate == "works_at"
    assert retrieved_edge.is_superseded is False

    active_edges = temp_store.get_edges_by_source_predicate("node_user_01", "works_at", active_only=True)
    assert len(active_edges) == 1
    assert active_edges[0].edge_id == "edge_001"


def test_mutually_exclusive_fact_conflict_reconciliation(temp_store: SqliteTemporalGraphStore) -> None:
    """Verifies that inserting a mutually exclusive fact automatically supersedes older conflicting facts."""
    reconciler = TemporalFactConflictReconciler()
    time_t0 = datetime.now(UTC) - timedelta(days=60)
    time_t1 = datetime.now(UTC)

    # 1. Alice initially works at Company A (60 days ago)
    edge_old = TemporalFactEdge(
        edge_id="edge_work_old",
        source_id="user_alice",
        target_id="company_alpha",
        predicate="works_at",
        valid_from=time_t0,
        confidence_score=0.95,
    )
    res_initial = reconciler.resolve_and_insert(temp_store, edge_old)
    assert res_initial.is_conflict_detected is False
    assert len(res_initial.superseded_edges) == 0

    # 2. Alice changes job to Company B today
    edge_new = TemporalFactEdge(
        edge_id="edge_work_new",
        source_id="user_alice",
        target_id="company_beta",
        predicate="works_at",
        valid_from=time_t1,
        confidence_score=1.0,
    )
    res_update = reconciler.resolve_and_insert(temp_store, edge_new)
    assert res_update.is_conflict_detected is True
    assert len(res_update.superseded_edges) == 1
    assert res_update.superseded_edges[0].edge_id == "edge_work_old"

    # 3. Verify in store that old edge is superseded and has lineage pointer
    stored_old = temp_store.get_edge("edge_work_old")
    assert stored_old is not None
    assert stored_old.is_superseded is True
    assert stored_old.superseded_by == "edge_work_new"
    assert stored_old.valid_until == time_t1

    # 4. Active edges only return Company B
    active_facts = temp_store.get_edges_by_source_predicate("user_alice", "works_at", active_only=True)
    assert len(active_facts) == 1
    assert active_facts[0].target_id == "company_beta"

    # 5. Lineage traversal verifies history tracking
    lineage = reconciler.get_supersession_lineage(temp_store, "edge_work_new")
    assert len(lineage) == 2
    assert lineage[0].edge_id == "edge_work_new"
    assert lineage[1].edge_id == "edge_work_old"


def test_temporal_half_life_decay_and_access_reinforcement() -> None:
    """Verifies exponential decay over time, superseded penalties, and retrieval access reinforcement."""
    scorer = TemporalDecayScorer(half_life_days=30.0, superseded_penalty=0.1)
    now = datetime.now(UTC)

    # 1. Fresh active edge (0 days elapsed)
    edge_fresh = TemporalFactEdge(
        edge_id="edge_fresh",
        source_id="u1",
        target_id="t1",
        predicate="current_framework",
        valid_from=now,
        confidence_score=1.0,
    )
    score_fresh, status_fresh = scorer.calculate_score(edge_fresh, as_of=now)
    assert status_fresh == "active"
    assert score_fresh == 1.0

    # 2. Edge from 60 days ago (2 half-lives elapsed -> decay factor 0.25)
    edge_decayed = TemporalFactEdge(
        edge_id="edge_decayed",
        source_id="u1",
        target_id="t1",
        predicate="current_framework",
        valid_from=now - timedelta(days=60),
        confidence_score=1.0,
    )
    score_decayed, status_decayed = scorer.calculate_score(edge_decayed, as_of=now)
    assert status_decayed == "active"
    assert 0.24 <= score_decayed <= 0.26

    # 3. Superseded edge receives severe penalty
    edge_superseded = TemporalFactEdge(
        edge_id="edge_sup",
        source_id="u1",
        target_id="t1",
        predicate="current_framework",
        valid_from=now,
        is_superseded=True,
        confidence_score=1.0,
    )
    score_sup, status_sup = scorer.calculate_score(edge_superseded, as_of=now)
    assert status_sup == "superseded"
    assert score_sup == 0.1

    # 4. Access reinforcement bonus
    scorer.record_access(edge_decayed, access_time=now)
    scorer.record_access(edge_decayed, access_time=now)
    assert edge_decayed.access_count == 2
    score_reinforced, _ = scorer.calculate_score(edge_decayed, as_of=now)
    # Since access_time is now, decay elapsed is 0 and bonus is applied
    assert score_reinforced > 1.0 or score_reinforced == 1.0
