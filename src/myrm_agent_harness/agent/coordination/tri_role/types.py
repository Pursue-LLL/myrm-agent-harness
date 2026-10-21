"""Domain types and contracts for Planner-Generator-Evaluator Tri-Role Separation
and Cross-Session Artifact Handoff Pipeline (Item 40).

[INPUT]
- Tri-role specifications, acceptance criteria, pipeline stage transitions,
  and cross-session artifact manifests.

[OUTPUT]
- Strongly-typed models for TriRoleType, StageStatus, AcceptanceCriterion,
  EvaluationVerdict, ArtifactManifest, TriRolePipelineStage, and TriRoleSessionState.

[POS]
- Harness coordination layer contracts for tri-role cognitive separation and artifact handoff.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import UTC, datetime


class TriRoleType(enum.StrEnum):
    """Cognitively separated multi-agent roles preventing self-delusion."""

    PLANNER = "planner"
    GENERATOR = "generator"
    EVALUATOR = "evaluator"


class StageStatus(enum.StrEnum):
    """Lifecycle progress status for a pipeline stage."""

    PLANNED = "planned"
    GENERATING = "generating"
    EVALUATING = "evaluating"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


@dataclass(frozen=True)
class AcceptanceCriterion:
    """Deterministic acceptance assertion formulated by the Planner."""

    criterion_id: str
    description: str
    assertion_rule: str
    is_satisfied: bool = False


@dataclass(frozen=True)
class EvaluationVerdict:
    """Independent adversary verdict rendered by the Scalable Evaluator."""

    is_accepted: bool
    score: float
    evaluator_notes: str
    criteria_results: dict[str, bool] = field(default_factory=dict)
    evaluated_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))


@dataclass(frozen=True)
class ArtifactManifest:
    """Standardized cross-session artifact package enabling zero-loss handoff."""

    manifest_id: str
    session_id: str
    stage_index: int
    produced_files: list[str] = field(default_factory=list)
    passed_assertions: list[str] = field(default_factory=list)
    key_constraints: list[str] = field(default_factory=list)
    pending_todos: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))


@dataclass(frozen=True)
class TriRolePipelineStage:
    """Single discrete horizon step governed by tri-role checks and balances."""

    stage_id: str
    stage_name: str
    status: StageStatus = StageStatus.PLANNED
    planner_output: str = ""
    criteria: list[AcceptanceCriterion] = field(default_factory=list)
    generator_output: str = ""
    produced_files: list[str] = field(default_factory=list)
    evaluation: EvaluationVerdict | None = None
    manifest: ArtifactManifest | None = None


@dataclass(frozen=True)
class TriRoleSessionState:
    """Consolidated state of a tri-role long-horizon orchestration session."""

    session_id: str
    task_description: str
    stages: list[TriRolePipelineStage] = field(default_factory=list)
    current_stage_index: int = 0
    is_completed: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
