"""Deep edge case and topological boundary tests for bitemporal truth maintenance."""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.bitemporal_truth_maintenance import (
    BitemporalCoordinates,
    BitemporalTruthMaintenanceFacade,
    EvidenceRecord,
    EvidenceType,
    SupportDependency,
    TemporalQueryCriteria,
    TruthMaintenanceGraph,
    create_interval,
    intersect_intervals,
    span_intervals,
)


def test_zero_length_and_adjacent_half_open_intervals() -> None:
    """Tests zero-length intervals [t, t) and strictly adjacent non-overlapping boundaries."""
    # 1. Zero-length interval [10.0, 10.0) is mathematically empty
    zero_inv = create_interval(10.0, 10.0)
    assert not zero_inv.contains(10.0)
    assert not zero_inv.contains(9.99)
    assert not zero_inv.contains(10.01)

    # 2. Strict adjacent intervals [0, 10) and [10, 20)
    inv_left = create_interval(0.0, 10.0)
    inv_right = create_interval(10.0, 20.0)

    # Point 10.0 is strictly NOT in left, but IS in right
    assert not inv_left.contains(10.0)
    assert inv_right.contains(10.0)

    # Overlap and intersection between adjacent intervals is strictly None
    assert not inv_left.overlaps(inv_right)
    assert intersect_intervals(inv_left, inv_right) is None


def test_negative_timestamps_and_multi_interval_spanning() -> None:
    """Tests intervals spanning across negative epoch boundaries and multi-interval span."""
    # 1. Negative interval [-100.0, -20.0)
    neg_inv = create_interval(-100.0, -20.0)
    assert neg_inv.contains(-50.0)
    assert not neg_inv.contains(-100.1)
    assert not neg_inv.contains(-20.0)

    # 2. Crossing zero [-30.0, 30.0)
    zero_cross = create_interval(-30.0, 30.0)
    assert zero_cross.contains(0.0)

    # 3. Span across multiple intervals (bounded and unbounded)
    i1 = create_interval(-50.0, -10.0)
    i2 = create_interval(0.0, 40.0)
    i3 = create_interval(50.0, 100.0)
    spanned_bounded = span_intervals([i1, i2, i3])
    assert spanned_bounded is not None
    assert spanned_bounded.start == -50.0
    assert spanned_bounded.end == 100.0

    i_unbounded = create_interval(80.0, None)
    spanned_unbounded = span_intervals([i1, i2, i_unbounded])
    assert spanned_unbounded is not None
    assert spanned_unbounded.start == -50.0
    assert spanned_unbounded.is_unbounded_end


def test_diamond_dependency_and_disjunctive_support() -> None:
    """Tests diamond dependency topology and disjunctive (alternative) justification paths."""
    graph = TruthMaintenanceGraph()

    # Ground Facts: Root F0 and alternative backup F_backup
    f0 = EvidenceRecord(
        evidence_id="f0",
        content="Primary root fact",
        evidence_type=EvidenceType.FACT,
        bitemporal=BitemporalCoordinates(
            valid_interval=create_interval(0.0),
            known_interval=create_interval(0.0),
        ),
    )
    f_backup = EvidenceRecord(
        evidence_id="f_backup",
        content="Secondary backup fact",
        evidence_type=EvidenceType.FACT,
        bitemporal=BitemporalCoordinates(
            valid_interval=create_interval(0.0),
            known_interval=create_interval(0.0),
        ),
    )

    # Inferences forming diamond: F0 -> Left & Right -> Apex
    inf_left = EvidenceRecord(
        evidence_id="inf_left",
        content="Left branch inference",
        evidence_type=EvidenceType.INFERENCE,
        bitemporal=BitemporalCoordinates(
            valid_interval=create_interval(0.0),
            known_interval=create_interval(0.0),
        ),
    )
    inf_right = EvidenceRecord(
        evidence_id="inf_right",
        content="Right branch inference",
        evidence_type=EvidenceType.INFERENCE,
        bitemporal=BitemporalCoordinates(
            valid_interval=create_interval(0.0),
            known_interval=create_interval(0.0),
        ),
    )
    inf_apex = EvidenceRecord(
        evidence_id="inf_apex",
        content="Apex converging inference",
        evidence_type=EvidenceType.INFERENCE,
        bitemporal=BitemporalCoordinates(
            valid_interval=create_interval(0.0),
            known_interval=create_interval(0.0),
        ),
    )

    graph.add_record(f0)
    graph.add_record(f_backup)
    graph.add_record(inf_left)
    graph.add_record(inf_right)
    graph.add_record(inf_apex)

    # Diamond wiring
    graph.add_support_dependency(
        SupportDependency(inference_id="inf_left", premise_ids=("f0",), causal_distance=1)
    )
    graph.add_support_dependency(
        SupportDependency(inference_id="inf_right", premise_ids=("f0",), causal_distance=1)
    )
    # Apex primary justification: requires BOTH left and right
    graph.add_support_dependency(
        SupportDependency(
            inference_id="inf_apex",
            premise_ids=("inf_left", "inf_right"),
            causal_distance=1,
            justification="Requires both left and right confirmation",
        )
    )

    # Initial assertion holds
    assert graph.is_record_active_at("inf_apex", valid_time=10.0, known_time=10.0)

    # Retract right branch: Apex loses primary support
    graph.retract_record("inf_right", retracted_at=20.0)
    assert not graph.is_record_active_at("inf_apex", valid_time=25.0, known_time=25.0)

    # Add alternative disjunctive justification to Apex: supported directly by f_backup!
    graph.add_support_dependency(
        SupportDependency(
            inference_id="inf_apex",
            premise_ids=("f_backup",),
            causal_distance=1,
            justification="Alternative path via backup fact",
        )
    )
    # With alternative active path available, Apex recovers active support!
    assert graph.is_record_active_at("inf_apex", valid_time=25.0, known_time=25.0)


def test_deep_causal_chain_and_indirect_circularity() -> None:
    """Tests 5-tier deep causal chain and multi-hop circular reasoning loop prevention."""
    graph = TruthMaintenanceGraph()

    # Create chain: F -> I1 -> I2 -> I3 -> I4 -> I5
    f_root = EvidenceRecord(
        evidence_id="root",
        content="Ground truth root",
        evidence_type=EvidenceType.FACT,
        bitemporal=BitemporalCoordinates(
            valid_interval=create_interval(0.0),
            known_interval=create_interval(0.0),
        ),
    )
    graph.add_record(f_root)

    prev_id = "root"
    for i in range(1, 6):
        cur_id = f"i{i}"
        rec = EvidenceRecord(
            evidence_id=cur_id,
            content=f"Inference level {i}",
            evidence_type=EvidenceType.INFERENCE,
            bitemporal=BitemporalCoordinates(
                valid_interval=create_interval(0.0),
                known_interval=create_interval(0.0),
            ),
        )
        graph.add_record(rec)
        graph.add_support_dependency(
            SupportDependency(inference_id=cur_id, premise_ids=(prev_id,), causal_distance=1)
        )
        prev_id = cur_id

    # Depth of i5 must be 5
    assert graph.calculate_causal_distance("i5") == 5
    assert graph.is_record_active_at("i5", valid_time=10.0, known_time=10.0)

    # Retract root at t=30: all 5 cascade to inactive
    graph.retract_record("root", retracted_at=30.0)
    for i in range(1, 6):
        assert not graph.is_record_active_at(f"i{i}", valid_time=35.0, known_time=35.0)

    # Test indirect multi-hop cycle: I3 depends on I5 (forming I3 -> I4 -> I5 -> I3)
    graph.add_support_dependency(
        SupportDependency(inference_id="i3", premise_ids=("i5",), causal_distance=1)
    )
    # Cycle guard prevents recursion error and circular justification cannot revive inactive truth
    assert not graph.has_active_support("i3", valid_time=35.0, known_time=35.0)

    # Isolated closed-loop cycle without any ground truth (c1 -> c2 -> c1)
    c1 = EvidenceRecord(
        evidence_id="c1",
        content="Cycle node 1",
        evidence_type=EvidenceType.INFERENCE,
        bitemporal=BitemporalCoordinates(
            valid_interval=create_interval(0.0),
            known_interval=create_interval(0.0),
        ),
    )
    c2 = EvidenceRecord(
        evidence_id="c2",
        content="Cycle node 2",
        evidence_type=EvidenceType.INFERENCE,
        bitemporal=BitemporalCoordinates(
            valid_interval=create_interval(0.0),
            known_interval=create_interval(0.0),
        ),
    )
    graph.add_record(c1)
    graph.add_record(c2)
    graph.add_support_dependency(
        SupportDependency(inference_id="c1", premise_ids=("c2",), causal_distance=1)
    )
    graph.add_support_dependency(
        SupportDependency(inference_id="c2", premise_ids=("c1",), causal_distance=1)
    )
    assert not graph.has_active_support("c1", valid_time=10.0, known_time=10.0)
    assert not graph.has_active_support("c2", valid_time=10.0, known_time=10.0)


def test_orphan_premises_and_idempotent_retraction() -> None:
    """Tests dangling/orphan premise references and redundant retraction handling."""
    graph = TruthMaintenanceGraph()

    orphan_inf = EvidenceRecord(
        evidence_id="inf_orphan",
        content="Inference pointing to non-existent premise",
        evidence_type=EvidenceType.INFERENCE,
        bitemporal=BitemporalCoordinates(
            valid_interval=create_interval(0.0),
            known_interval=create_interval(0.0),
        ),
    )
    graph.add_record(orphan_inf)
    graph.add_support_dependency(
        SupportDependency(
            inference_id="inf_orphan",
            premise_ids=("fact_ghost_404",),
            causal_distance=1,
        )
    )

    # Missing premise should gracefully evaluate to False without raising exceptions
    assert not graph.is_record_active_at("inf_orphan", valid_time=10.0, known_time=10.0)

    # Idempotent retraction of non-existent record
    assert graph.retract_record("ghost_record", retracted_at=50.0) is False

    # Idempotent retraction of already retracted record
    rec = EvidenceRecord(
        evidence_id="normal_rec",
        content="Normal fact",
        evidence_type=EvidenceType.FACT,
        bitemporal=BitemporalCoordinates(
            valid_interval=create_interval(10.0),
            known_interval=create_interval(10.0),
        ),
    )
    graph.add_record(rec)
    # Attempting to retract prior to known start (10.0) is rejected
    assert graph.retract_record("normal_rec", retracted_at=5.0) is False

    # Valid retraction at 20.0
    assert graph.retract_record("normal_rec", retracted_at=20.0) is True

    # Secondary retraction attempts are immutable and return False
    assert graph.retract_record("normal_rec", retracted_at=15.0) is False
    assert graph.retract_record("normal_rec", retracted_at=20.0) is False
    assert graph.retract_record("normal_rec", retracted_at=30.0) is False


def test_multi_criteria_query_filtering_deep() -> None:
    """Tests rich filtering by confidence, evidence types, and active support flags."""
    facade = BitemporalTruthMaintenanceFacade()

    facade.record_fact(
        "fact_high_conf",
        "High confidence verified fact",
        valid_start=0.0,
        known_start=0.0,
        confidence=0.95,
    )
    facade.record_fact(
        "fact_low_conf",
        "Speculative unverified observation",
        valid_start=0.0,
        known_start=0.0,
        confidence=0.40,
    )

    facade.derive_inference(
        "inf_high",
        "High confidence derived inference",
        premise_ids=["fact_high_conf"],
        justification="Sound premise",
        valid_start=0.0,
        known_start=0.0,
        confidence=0.90,
    )

    # Query with minimum confidence 0.8: should exclude fact_low_conf
    criteria_conf = TemporalQueryCriteria(
        min_confidence=0.8,
        require_active_support=True,
    )
    res_conf = facade.query_active(criteria_conf)
    ids_conf = {r.evidence_id for r in res_conf}
    assert ids_conf == {"fact_high_conf", "inf_high"}

    # Query filtering strictly by EvidenceType.INFERENCE
    criteria_type = TemporalQueryCriteria(
        evidence_types=(EvidenceType.INFERENCE,),
        require_active_support=True,
    )
    res_type = facade.query_active(criteria_type)
    ids_type = {r.evidence_id for r in res_type}
    assert ids_type == {"inf_high"}
