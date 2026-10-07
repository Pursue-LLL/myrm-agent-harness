# [POS]: tests/unit/toolkits/memory/test_fact_supersession_suite.py
# [INPUT]: myrm_agent_harness.toolkits.memory.fact_supersession
# [OUTPUT]: Unit tests for FactSupersessionTemporalValidityAndContradictionLedgerSuite (Item 102)

from __future__ import annotations

from myrm_agent_harness.toolkits.memory import (
    ContradictionQuarantineGate,
    DialecticRecallProjector,
    FactSupersessionChainEngine,
    TemporalFactRecord,
    TemporalFactStatus,
)


def test_explicit_supersession_chain_and_time_travel() -> None:
    """Validate explicit supersession chain creation and time-travel as-of point-in-time queries."""
    engine = FactSupersessionChainEngine()

    # 1. Record initial fact: User tech stack is Python (starting 2026-01-01)
    fact1 = TemporalFactRecord(
        fact_id="fact-tech-01",
        subject="User",
        predicate="primary_tech_stack",
        object_value="Python",
        valid_from="2026-01-01T00:00:00Z",
        confidence=1.0,
        evidence_quote="I mainly code in Python for all backend tasks.",
    )
    engine.record_fact(fact1)

    # 2. Supersede with new fact: User switched to Rust on 2026-09-01
    fact2 = TemporalFactRecord(
        fact_id="fact-tech-02",
        subject="User",
        predicate="primary_tech_stack",
        object_value="Rust",
        valid_from="2026-09-01T00:00:00Z",
        confidence=1.0,
        evidence_quote="Starting this September, I am migrating everything to Rust.",
    )
    old_f, new_f = engine.supersede("fact-tech-01", fact2)

    # Validate interval closure and linkage
    assert old_f.status == TemporalFactStatus.SUPERSEDED
    assert old_f.valid_until == "2026-09-01T00:00:00Z"
    assert old_f.superseded_by == "fact-tech-02"

    assert new_f.status == TemporalFactStatus.ACTIVE
    assert new_f.valid_until is None

    # 3. Query current active: should only return Rust
    active_facts = engine.query_active(subject="User", predicate="primary_tech_stack")
    assert len(active_facts) == 1
    assert active_facts[0].object_value == "Rust"

    # 4. Time-travel query: As of June 2026 -> should return Python
    past_facts = engine.query_as_of("2026-06-01T12:00:00Z", subject="User", predicate="primary_tech_stack")
    assert len(past_facts) == 1
    assert past_facts[0].object_value == "Python"
    assert past_facts[0].fact_id == "fact-tech-01"

    # 5. Time-travel query: As of October 2026 -> should return Rust
    future_facts = engine.query_as_of("2026-10-01T12:00:00Z", subject="User", predicate="primary_tech_stack")
    assert len(future_facts) == 1
    assert future_facts[0].object_value == "Rust"
    assert future_facts[0].fact_id == "fact-tech-02"

    # 6. Trace ancestor lineage
    history = engine.get_supersession_history("fact-tech-02")
    assert len(history) == 1
    assert history[0].fact_id == "fact-tech-01"


def test_contradiction_quarantine_gate_and_human_review() -> None:
    """Validate contradiction detection, quarantine isolation of low-confidence candidates, and human review."""
    engine = FactSupersessionChainEngine()
    gate = ContradictionQuarantineGate(conflict_threshold=0.85)

    # 1. Active fact: Remote work is Full Remote
    base_fact = TemporalFactRecord(
        fact_id="fact-policy-01",
        subject="Company",
        predicate="remote_policy",
        object_value="Full Remote",
        valid_from="2026-01-01T00:00:00Z",
        confidence=1.0,
    )
    status, _ = gate.ingest_fact(base_fact, engine)
    assert status == "RECORDED"

    # 2. Ingest low-confidence contradiction (confidence=0.65 < threshold 0.85)
    guess_fact = TemporalFactRecord(
        fact_id="fact-policy-guess",
        subject="Company",
        predicate="remote_policy",
        object_value="Hybrid 2 Days",
        valid_from="2026-10-01T00:00:00Z",
        confidence=0.65,
    )
    status2, q_item = gate.ingest_fact(guess_fact, engine)
    assert status2 == "QUARANTINED"
    assert q_item.conflicting_fact_id == "fact-policy-01"
    assert q_item.status == "quarantined"

    # Verify active fact is untouched
    active = engine.query_active(subject="Company", predicate="remote_policy")
    assert len(active) == 1
    assert active[0].object_value == "Full Remote"

    # 3. Human review: Approve override
    success, approved_fact = gate.resolve_quarantine(
        q_item.quarantine_id,
        approve_override=True,
        chain_engine=engine,
    )
    assert success is True
    assert approved_fact is not None
    assert approved_fact.object_value == "Hybrid 2 Days"

    # Now Hybrid 2 Days is active, Full Remote is superseded
    active_now = engine.query_active(subject="Company", predicate="remote_policy")
    assert len(active_now) == 1
    assert active_now[0].object_value == "Hybrid 2 Days"


def test_dialectic_recall_projection() -> None:
    """Validate dialectic recall projector attaching ancestral supersession lineage for explainability."""
    engine = FactSupersessionChainEngine()
    projector = DialecticRecallProjector()

    # Setup evolution: v1 -> v2 -> v3
    f1 = TemporalFactRecord(
        fact_id="f-01",
        subject="Project",
        predicate="database",
        object_value="SQLite",
        valid_from="2026-01-01T00:00:00Z",
        confidence=1.0,
    )
    f2 = TemporalFactRecord(
        fact_id="f-02",
        subject="Project",
        predicate="database",
        object_value="PostgreSQL",
        valid_from="2026-05-01T00:00:00Z",
        confidence=1.0,
    )
    f3 = TemporalFactRecord(
        fact_id="f-03",
        subject="Project",
        predicate="database",
        object_value="Distributed Qdrant + PG",
        valid_from="2026-09-01T00:00:00Z",
        confidence=1.0,
    )

    engine.record_fact(f1)
    engine.supersede("f-01", f2)
    engine.supersede("f-02", f3)

    # Dialectic projection for current state
    projection = projector.project_recall(engine, subject="Project", predicate="database")

    assert projection.total_matched == 1
    assert projection.active_facts[0].fact_id == "f-03"
    assert projection.active_facts[0].object_value == "Distributed Qdrant + PG"

    # Lineage must capture ancestors f-02 and f-01
    lineage = projection.superseded_lineage["f-03"]
    assert len(lineage) == 2
    ancestor_ids = [a.fact_id for a in lineage]
    assert ancestor_ids == ["f-02", "f-01"]
