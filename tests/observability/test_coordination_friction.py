"""
Tests for human coordination friction metrics and supervision decay curve tracking.
"""

from myrm_agent_harness.observability.coordination_friction.friction_tracker import (
    CoordinationFrictionTracker,
)
from myrm_agent_harness.observability.coordination_friction.models import (
    CoordinationScoreboardSummary,
    InterventionType,
    SupervisionDecayPoint,
    TaskFrictionRecord,
)


def test_record_task_friction_and_density_rate() -> None:
    tracker = CoordinationFrictionTracker()

    rec = tracker.record_task_friction(
        task_id="task-deal-001",
        template_type="channel_deal",
        execution_sequence=1,
        total_substeps=20,
        intervention_count=4,
        rework_count=1,
        human_attention_minutes=35.0,
        timestamp=100.0,
    )

    # 4 interventions in 20 substeps -> (4 / 20) * 10 = 2.0
    assert rec.friction_rate == 2.0
    assert rec.total_substeps == 20
    assert rec.rework_count == 1
    assert rec.human_attention_minutes == 35.0


def test_supervision_decay_curve_computation() -> None:
    tracker = CoordinationFrictionTracker()
    template = "broadcast_prep"

    # Sequence 1: 10 steps, 8 interventions (80%), 40 mins
    tracker.record_task_friction(
        task_id="task-prep-1",
        template_type=template,
        execution_sequence=1,
        total_substeps=10,
        intervention_count=8,
        rework_count=1,
        human_attention_minutes=40.0,
    )

    # Sequence 2: 10 steps, 4 interventions (40%), 20 mins
    tracker.record_task_friction(
        task_id="task-prep-2",
        template_type=template,
        execution_sequence=2,
        total_substeps=10,
        intervention_count=4,
        rework_count=0,
        human_attention_minutes=20.0,
    )

    # Sequence 3: 10 steps, 1 intervention (10%), 8 mins
    tracker.record_task_friction(
        task_id="task-prep-3",
        template_type=template,
        execution_sequence=3,
        total_substeps=10,
        intervention_count=1,
        rework_count=0,
        human_attention_minutes=8.0,
    )

    decay_points = tracker.compute_decay_curve(template)
    assert len(decay_points) == 3
    assert decay_points[0].sequence_number == 1
    assert decay_points[0].intervention_rate_pct == 80.0
    assert decay_points[1].sequence_number == 2
    assert decay_points[1].intervention_rate_pct == 40.0
    assert decay_points[2].sequence_number == 3
    assert decay_points[2].intervention_rate_pct == 10.0

    summary = tracker.get_template_summary(template)
    assert summary.total_runs == 3
    # Decay from 80% to 10%: ((10 - 80) / 80) * 100 = -87.5%
    assert summary.friction_decay_pct == -87.5
    # Saved: (40-40) + (40-20) + (40-8) = 0 + 20 + 32 = 52 minutes = 0.87 hours
    assert abs(summary.total_coordination_hours_saved - (52.0 / 60.0)) < 0.05
    assert summary.rework_rate_pct == 33.33  # 1 rework out of 3 runs


def test_global_summary_aggregation() -> None:
    tracker = CoordinationFrictionTracker()

    tracker.record_task_friction(
        task_id="t1",
        template_type="tmpl_a",
        execution_sequence=1,
        total_substeps=10,
        intervention_count=5,
        rework_count=0,
        human_attention_minutes=25.0,
    )
    tracker.record_task_friction(
        task_id="t2",
        template_type="tmpl_b",
        execution_sequence=1,
        total_substeps=10,
        intervention_count=6,
        rework_count=1,
        human_attention_minutes=30.0,
    )

    summary = tracker.get_global_summary()
    assert summary.template_type == "global"
    assert summary.total_runs == 2
    assert summary.rework_rate_pct == 50.0
    assert len(summary.decay_curve) == 1
    assert summary.decay_curve[0].sequence_number == 1
    assert summary.decay_curve[0].sample_count == 2
