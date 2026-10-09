"""Unit and integration tests for bitemporal truth maintenance filter suite."""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.memory.bitemporal_truth_maintenance import (
    BitemporalCoordinates,
    BitemporalTruthMaintenanceFacade,
    EvidenceRecord,
    EvidenceType,
    SupportDependency,
    TemporalQueryCriteria,
    TimeInterval,
    TruthMaintenanceGraph,
    create_interval,
    get_bitemporal_truth_maintenance_facade,
    intersect_intervals,
    shift_interval,
    span_intervals,
)


def test_half_open_interval_calculus() -> None:
    """Test mathematically rigorous [start, end) half-open interval calculus."""
    # 1. Closed bounded half-open interval [10, 20)
    inv = create_interval(10.0, 20.0)
    assert not inv.contains(9.99)
    assert inv.contains(10.0)  # inclusive start
    assert inv.contains(15.0)
    assert not inv.contains(20.0)  # exclusive end
    assert not inv.contains(20.01)
    assert not inv.is_unbounded_end

    # 2. Positive-infinity unbounded interval [50, +inf)
    unbounded = create_interval(50.0, None)
    assert not unbounded.contains(49.99)
    assert unbounded.contains(50.0)
    assert unbounded.contains(9999999.0)
    assert unbounded.is_unbounded_end

    # 3. Invalid interval constructor
    with pytest.raises(ValueError, match=r"start .* cannot exceed end"):
        TimeInterval(start=100.0, end=50.0)

    # 4. Overlap & Intersection
    inv_a = create_interval(10.0, 30.0)
    inv_b = create_interval(20.0, 40.0)
    assert inv_a.overlaps(inv_b)
    intersection = intersect_intervals(inv_a, inv_b)
    assert intersection is not None
    assert intersection.start == 20.0
    assert intersection.end == 30.0

    # Disjoint intersection
    inv_c = create_interval(30.0, 50.0)
    assert intersect_intervals(inv_a, inv_c) is None

    # 5. Span and Shift
    spanned = span_intervals([inv_a, inv_b])
    assert spanned is not None
    assert spanned.start == 10.0
    assert spanned.end == 40.0

    shifted = shift_interval(inv_a, 5.0)
    assert shifted.start == 15.0
    assert shifted.end == 35.0


def test_bitemporal_coordinates_activation() -> None:
    """Test point-in-time activation across dual valid and known dimensions."""
    coords = BitemporalCoordinates(
        valid_interval=create_interval(100.0, 200.0),  # Valid in world: 100~200
        known_interval=create_interval(110.0, 180.0),  # System believed: 110~180
    )

    # Both valid and known
    assert coords.is_active_at(valid_time=150.0, known_time=150.0)

    # Valid in world, but unknown to system yet
    assert not coords.is_active_at(valid_time=150.0, known_time=105.0)

    # Known by system, but invalid in world yet
    assert not coords.is_active_at(valid_time=90.0, known_time=150.0)

    # Known after retraction
    assert not coords.is_active_at(valid_time=150.0, known_time=180.0)


def test_nondestructive_retraction() -> None:
    """Test non-destructive retraction preserves historical data for time-travel queries."""
    graph = TruthMaintenanceGraph()
    record = EvidenceRecord(
        evidence_id="fact-email",
        content="User email is old@domain.com",
        evidence_type=EvidenceType.FACT,
        bitemporal=BitemporalCoordinates(
            valid_interval=create_interval(100.0, None),
            known_interval=create_interval(100.0, None),
        ),
    )
    graph.add_record(record)

    # Retract the email assertion at t=300
    retracted = graph.retract_record("fact-email", retracted_at=300.0)
    assert retracted is True

    # Secondary retraction at later timestamp is rejected
    assert graph.retract_record("fact-email", retracted_at=400.0) is False

    # Historical inquiry at t=250 (prior to retraction): Record remains active and valid!
    assert graph.is_record_active_at("fact-email", valid_time=250.0, known_time=250.0)

    # Contemporary inquiry at t=350: Record is recognized as retracted!
    assert not graph.is_record_active_at("fact-email", valid_time=350.0, known_time=350.0)

    # Physical record is preserved!
    persisted = graph.get_record("fact-email")
    assert persisted is not None
    assert persisted.is_retracted(as_of_known_time=350.0) is True


def test_tms_active_support_cascade_invalidation() -> None:
    """Test TMS recursive justification cascade when supporting premise is retracted."""
    facade = BitemporalTruthMaintenanceFacade()

    # 1. Ground Facts
    facade.record_fact(
        evidence_id="fact-role",
        content="User is Senior SRE",
        valid_start=100.0,
        known_start=100.0,
    )
    facade.record_fact(
        evidence_id="fact-clearance",
        content="User holds production root credential",
        valid_start=100.0,
        known_start=100.0,
    )

    # 2. Derived Inference supported by both facts
    facade.derive_inference(
        inference_id="inf-prod-access",
        content="User is authorized to deploy production services",
        premise_ids=["fact-role", "fact-clearance"],
        justification="Role requirements and credential verification met",
        valid_start=100.0,
        known_start=100.0,
        causal_distance=1,
    )

    # Initial state: Inference holds active support
    assert facade.graph.is_record_active_at(
        "inf-prod-access", valid_time=150.0, known_time=150.0
    )

    # 3. Non-destructively retract clearance at t=200
    facade.retract_record("fact-clearance", retracted_at=200.0)

    # At t=150 (historical inspection): Active support still holds
    assert facade.graph.is_record_active_at(
        "inf-prod-access", valid_time=150.0, known_time=150.0
    )

    # At t=250: Inference automatically loses active support!
    assert not facade.graph.is_record_active_at(
        "inf-prod-access", valid_time=250.0, known_time=250.0
    )

    # Underlying record remains preserved in graph
    inf_rec = facade.graph.get_record("inf-prod-access")
    assert inf_rec is not None
    assert inf_rec.evidence_id == "inf-prod-access"


def test_multi_hop_causal_distance_and_circular_guard() -> None:
    """Test multi-hop causal distance calculation and circular reasoning prevention."""
    graph = TruthMaintenanceGraph()

    # Fact -> Inf1 -> Inf2
    r_fact = EvidenceRecord(
        evidence_id="f1",
        content="Ground fact",
        evidence_type=EvidenceType.FACT,
        bitemporal=BitemporalCoordinates(
            valid_interval=create_interval(0.0),
            known_interval=create_interval(0.0),
        ),
    )
    r_inf1 = EvidenceRecord(
        evidence_id="i1",
        content="Inference tier 1",
        evidence_type=EvidenceType.INFERENCE,
        bitemporal=BitemporalCoordinates(
            valid_interval=create_interval(0.0),
            known_interval=create_interval(0.0),
        ),
    )
    r_inf2 = EvidenceRecord(
        evidence_id="i2",
        content="Inference tier 2",
        evidence_type=EvidenceType.INFERENCE,
        bitemporal=BitemporalCoordinates(
            valid_interval=create_interval(0.0),
            known_interval=create_interval(0.0),
        ),
    )
    graph.add_record(r_fact)
    graph.add_record(r_inf1)
    graph.add_record(r_inf2)

    graph.add_support_dependency(
        SupportDependency(inference_id="i1", premise_ids=("f1",), causal_distance=1)
    )
    graph.add_support_dependency(
        SupportDependency(inference_id="i2", premise_ids=("i1",), causal_distance=2)
    )

    # Causal distance
    assert graph.calculate_causal_distance("i1") == 1
    assert graph.calculate_causal_distance("i2") == 3  # 1 + 2

    # Circular loop simulation: i1 also depends on i2
    graph.add_support_dependency(
        SupportDependency(inference_id="i1", premise_ids=("i2",), causal_distance=1)
    )
    # Circle guard prevents infinite recursion and evaluates safely
    assert not graph.has_active_support("i1", valid_time=10.0, known_time=10.0, visited={"i1"})


def test_as_of_time_travel_filter_and_snapshot() -> None:
    """Test as-of time-travel query filtering and snapshot projection."""
    facade = BitemporalTruthMaintenanceFacade()

    # Fact 1: Active throughout
    facade.record_fact("f1", "Permanent fact", valid_start=0.0, known_start=0.0)

    # Fact 2: Active then retracted at t=50
    facade.record_fact("f2", "Temporary fact", valid_start=0.0, known_start=0.0)
    facade.retract_record("f2", retracted_at=50.0)

    # Inference depending on f2
    facade.derive_inference(
        "inf1",
        "Derived from temporary fact",
        premise_ids=["f2"],
        justification="Based on f2",
        valid_start=0.0,
        known_start=0.0,
    )

    # 1. Query at t=25 (both f1, f2, and inf1 are active)
    criteria_early = TemporalQueryCriteria(
        as_of_valid_time=25.0,
        as_of_known_time=25.0,
        require_active_support=True,
    )
    early_results = facade.query_active(criteria_early)
    early_ids = {r.evidence_id for r in early_results}
    assert early_ids == {"f1", "f2", "inf1"}

    # 2. Query at t=75 (f2 retracted -> inf1 loses support -> only f1 remains)
    criteria_late = TemporalQueryCriteria(
        as_of_valid_time=75.0,
        as_of_known_time=75.0,
        require_active_support=True,
    )
    late_results = facade.query_active(criteria_late)
    late_ids = {r.evidence_id for r in late_results}
    assert late_ids == {"f1"}

    # 3. Snapshot projection at t=75
    snap = facade.project_snapshot(as_of_valid_time=75.0, as_of_known_time=75.0)
    assert len(snap.active_evidences) == 1
    assert snap.active_evidences[0].evidence_id == "f1"
    assert len(snap.retracted_evidences) == 1
    assert snap.retracted_evidences[0].evidence_id == "f2"
    assert len(snap.invalidated_inferences) == 1
    assert snap.invalidated_inferences[0].evidence_id == "inf1"
    assert snap.total_count == 3


def test_global_singleton_accessor() -> None:
    """Test global singleton facade accessor."""
    inst1 = get_bitemporal_truth_maintenance_facade()
    inst2 = get_bitemporal_truth_maintenance_facade()
    assert inst1 is inst2
