"""
[INPUT]: TaskFrictionRecord entries and template categories.
[OUTPUT]: Aggregated coordination scoreboard and supervision decay curve calculations.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/coordination_friction/friction_tracker.py
"""

from collections import defaultdict
import time
from typing import Dict, List, Optional

from .models import (
    CoordinationScoreboardSummary,
    InterventionType,
    SupervisionDecayPoint,
    TaskFrictionRecord,
)


class CoordinationFrictionTracker:
    """
    Tracks human supervision friction, rework rates, and calculates
    empirical supervision decay curves for recurring agent workflows.
    """

    def __init__(self) -> None:
        # Map of template_type -> list of TaskFrictionRecord
        self._records_by_template: Dict[str, List[TaskFrictionRecord]] = defaultdict(list)

    def record_task_friction(
        self,
        task_id: str,
        template_type: str,
        execution_sequence: int,
        total_substeps: int,
        intervention_count: int,
        rework_count: int,
        human_attention_minutes: float,
        timestamp: Optional[float] = None,
    ) -> TaskFrictionRecord:
        """Records human coordination friction details for a task execution."""
        ts = timestamp if timestamp is not None else time.time()
        record = TaskFrictionRecord(
            task_id=task_id,
            template_type=template_type,
            execution_sequence=execution_sequence,
            total_substeps=total_substeps,
            intervention_count=intervention_count,
            rework_count=rework_count,
            human_attention_minutes=human_attention_minutes,
            timestamp=ts,
        )
        self._records_by_template[template_type].append(record)
        return record

    def compute_decay_curve(self, template_type: str) -> List[SupervisionDecayPoint]:
        """
        Computes the empirical supervision decay curve for a specific template type,
        grouping runs by their execution sequence (Run #1, Run #2, etc.).
        """
        records = self._records_by_template.get(template_type, [])
        if not records:
            return []

        grouped: Dict[int, List[TaskFrictionRecord]] = defaultdict(list)
        for r in records:
            grouped[r.execution_sequence].append(r)

        decay_points: List[SupervisionDecayPoint] = []
        for seq in sorted(grouped.keys()):
            items = grouped[seq]
            total_steps = sum(item.total_substeps for item in items)
            total_interventions = sum(item.intervention_count for item in items)
            total_minutes = sum(item.human_attention_minutes for item in items)

            rate_pct = (
                (total_interventions / total_steps) * 100.0
                if total_steps > 0
                else 0.0
            )
            avg_mins = total_minutes / len(items) if items else 0.0

            decay_points.append(
                SupervisionDecayPoint(
                    sequence_number=seq,
                    intervention_rate_pct=min(100.0, rate_pct),
                    average_attention_minutes=avg_mins,
                    sample_count=len(items),
                )
            )

        return decay_points

    def get_template_summary(self, template_type: str) -> CoordinationScoreboardSummary:
        """Produces a comprehensive friction scoreboard summary for a template."""
        records = self._records_by_template.get(template_type, [])
        if not records:
            return CoordinationScoreboardSummary(
                template_type=template_type,
                total_runs=0,
                average_friction_rate=0.0,
                rework_rate_pct=0.0,
                total_coordination_hours_saved=0.0,
                friction_decay_pct=0.0,
                decay_curve=[],
            )

        total_runs = len(records)
        avg_friction = sum(r.friction_rate for r in records) / total_runs
        rework_runs = sum(1 for r in records if r.rework_count > 0)
        rework_rate_pct = round((rework_runs / total_runs) * 100.0, 2)

        decay_curve = self.compute_decay_curve(template_type)

        # Compute friction decay reduction percentage: comparing first sequence to latest
        friction_decay_pct = 0.0
        if len(decay_curve) >= 2:
            first_rate = decay_curve[0].intervention_rate_pct
            last_rate = decay_curve[-1].intervention_rate_pct
            if first_rate > 0:
                friction_decay_pct = round(((last_rate - first_rate) / first_rate) * 100.0, 2)

        # Estimate coordination hours saved: baseline is 1st run attention minutes
        baseline_minutes = decay_curve[0].average_attention_minutes if decay_curve else 0.0
        saved_minutes = sum(
            max(0.0, baseline_minutes - r.human_attention_minutes) for r in records
        )
        saved_hours = round(saved_minutes / 60.0, 2)

        return CoordinationScoreboardSummary(
            template_type=template_type,
            total_runs=total_runs,
            average_friction_rate=avg_friction,
            rework_rate_pct=rework_rate_pct,
            total_coordination_hours_saved=saved_hours,
            friction_decay_pct=friction_decay_pct,
            decay_curve=decay_curve,
        )

    def get_global_summary(self) -> CoordinationScoreboardSummary:
        """Aggregates all recorded templates into a company-wide coordination scoreboard."""
        all_records: List[TaskFrictionRecord] = []
        for recs in self._records_by_template.values():
            all_records.extend(recs)

        if not all_records:
            return CoordinationScoreboardSummary(
                template_type="global",
                total_runs=0,
                average_friction_rate=0.0,
                rework_rate_pct=0.0,
                total_coordination_hours_saved=0.0,
                friction_decay_pct=0.0,
                decay_curve=[],
            )

        total_runs = len(all_records)
        avg_friction = round(sum(r.friction_rate for r in all_records) / total_runs, 2)
        rework_runs = sum(1 for r in all_records if r.rework_count > 0)
        rework_rate_pct = round((rework_runs / total_runs) * 100.0, 2)

        # Group all sequences for global decay curve
        grouped: Dict[int, List[TaskFrictionRecord]] = defaultdict(list)
        for r in all_records:
            grouped[r.execution_sequence].append(r)

        global_decay: List[SupervisionDecayPoint] = []
        for seq in sorted(grouped.keys()):
            items = grouped[seq]
            t_steps = sum(item.total_substeps for item in items)
            t_inter = sum(item.intervention_count for item in items)
            t_mins = sum(item.human_attention_minutes for item in items)
            r_pct = (t_inter / t_steps * 100.0) if t_steps > 0 else 0.0
            global_decay.append(
                SupervisionDecayPoint(
                    sequence_number=seq,
                    intervention_rate_pct=round(min(100.0, r_pct), 2),
                    average_attention_minutes=round(t_mins / len(items) if items else 0.0, 2),
                    sample_count=len(items),
                )
            )

        friction_decay_pct = 0.0
        if len(global_decay) >= 2:
            first_rate = global_decay[0].intervention_rate_pct
            last_rate = global_decay[-1].intervention_rate_pct
            if first_rate > 0:
                friction_decay_pct = round(((last_rate - first_rate) / first_rate) * 100.0, 2)

        baseline_minutes = global_decay[0].average_attention_minutes if global_decay else 0.0
        saved_minutes = sum(
            max(0.0, baseline_minutes - r.human_attention_minutes) for r in all_records
        )

        return CoordinationScoreboardSummary(
            template_type="global",
            total_runs=total_runs,
            average_friction_rate=avg_friction,
            rework_rate_pct=rework_rate_pct,
            total_coordination_hours_saved=round(saved_minutes / 60.0, 2),
            friction_decay_pct=friction_decay_pct,
            decay_curve=global_decay,
        )

