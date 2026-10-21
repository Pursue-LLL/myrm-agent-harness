"""
[INPUT]: Human-in-the-loop intervention events, rework signals, and task execution sequences.
[OUTPUT]: Strongly-typed telemetry models for coordination friction density and supervision decay curves.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/coordination_friction/models.py
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class InterventionType(str, Enum):
    """Categories of human supervision and friction during agent workflows."""

    APPROVAL_GATE = "APPROVAL_GATE"  # Mandatory or policy-triggered human gate
    STEER_CORRECTION = "STEER_CORRECTION"  # Human barge-in or steering mid-flight
    REJECT_REWORK = "REJECT_REWORK"  # Task output rejected; forced re-planning
    PARAMETER_OVERRIDE = "PARAMETER_OVERRIDE"  # Human manually changed task parameters


@dataclass(frozen=True)
class TaskFrictionRecord:
    """Record of human coordination costs for a single workflow execution run."""

    task_id: str
    template_type: str  # e.g., "channel_deal", "broadcast_prep", "code_refactor"
    execution_sequence: int  # 1st run, 2nd run, etc., for the same template
    total_substeps: int
    intervention_count: int
    rework_count: int
    human_attention_minutes: float
    timestamp: float

    @property
    def friction_rate(self) -> float:
        """Ratio of human interventions per 10 substeps (normalized friction density)."""
        if self.total_substeps <= 0:
            return 0.0
        return round((self.intervention_count / self.total_substeps) * 10.0, 2)

    def to_dict(self) -> Dict[str, object]:
        return {
            "task_id": self.task_id,
            "template_type": self.template_type,
            "execution_sequence": self.execution_sequence,
            "total_substeps": self.total_substeps,
            "intervention_count": self.intervention_count,
            "rework_count": self.rework_count,
            "human_attention_minutes": round(self.human_attention_minutes, 2),
            "friction_rate": self.friction_rate,
            "timestamp": round(self.timestamp, 3),
        }


@dataclass(frozen=True)
class SupervisionDecayPoint:
    """A data point on the repetitive task supervision decay curve."""

    sequence_number: int  # e.g., Run #1, Run #3, Run #5...
    intervention_rate_pct: float  # e.g., 100.0%, 65.0%, 20.0%, 8.0%
    average_attention_minutes: float
    sample_count: int

    def to_dict(self) -> Dict[str, object]:
        return {
            "sequence_number": self.sequence_number,
            "intervention_rate_pct": round(self.intervention_rate_pct, 2),
            "average_attention_minutes": round(self.average_attention_minutes, 2),
            "sample_count": self.sample_count,
        }


@dataclass(frozen=True)
class CoordinationScoreboardSummary:
    """Aggregate metrics reflecting tangible coordination friction reduction and ROI."""

    template_type: str  # "global" or specific template name
    total_runs: int
    average_friction_rate: float
    rework_rate_pct: float
    total_coordination_hours_saved: float
    friction_decay_pct: float  # e.g., -82.5% reduction from 1st run to latest
    decay_curve: List[SupervisionDecayPoint] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        return {
            "template_type": self.template_type,
            "total_runs": self.total_runs,
            "average_friction_rate": round(self.average_friction_rate, 2),
            "rework_rate_pct": round(self.rework_rate_pct, 2),
            "total_coordination_hours_saved": round(self.total_coordination_hours_saved, 2),
            "friction_decay_pct": round(self.friction_decay_pct, 2),
            "decay_curve": [p.to_dict() for p in self.decay_curve],
        }
