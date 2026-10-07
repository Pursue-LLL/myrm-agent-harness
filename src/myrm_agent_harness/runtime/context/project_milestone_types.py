"""Data contracts for long-horizon project milestone checkpoints and resumption.

Defines project phases, milestone decision registries, dependent TODO topologies,
incremental material delta packages, and continuous resumption bundles.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class MilestonePhaseKind(StrEnum):
    """Lifecycle phase of a long-horizon engineering or business project."""

    REQUIREMENTS_ANALYSIS = "requirements_analysis"
    ARCHITECTURE_DESIGN = "architecture_design"
    CORE_IMPLEMENTATION = "core_implementation"
    INTEGRATION_TESTING = "integration_testing"
    DEPLOYMENT_VERIFICATION = "deployment_verification"
    COMPLETED = "completed"


@dataclass(frozen=True, slots=True)
class MilestoneDecisionRecord:
    """Immutable architectural or business decision committed during a milestone."""

    decision_id: str
    title: str
    rationale: str
    accepted_at: float
    status: str = "active"


@dataclass(frozen=True, slots=True)
class ProjectTodoItem:
    """Executable action item with explicit dependency graph links."""

    todo_id: str
    title: str
    status: str = "pending"  # "pending" | "in_progress" | "resolved"
    depends_on: tuple[str, ...] = ()
    priority: str = "normal"  # "low" | "normal" | "high"


@dataclass(frozen=True, slots=True)
class IncrementalMaterialUpdate:
    """Extracted semantic diff when new documents or modified specs are injected."""

    material_id: str
    source_name: str
    new_requirements: tuple[str, ...] = ()
    modified_constraints: tuple[str, ...] = ()
    deprecated_items: tuple[str, ...] = ()
    injected_at: float = 0.0


@dataclass(frozen=True, slots=True)
class ProjectMilestoneCheckpoint:
    """Project-level persistent checkpoint snapshot surviving multi-week pauses."""

    checkpoint_id: str
    project_id: str
    phase: MilestonePhaseKind
    completed_milestones: tuple[str, ...] = ()
    active_decisions: tuple[MilestoneDecisionRecord, ...] = ()
    pending_todos: tuple[ProjectTodoItem, ...] = ()
    deliverable_files: tuple[str, ...] = ()
    material_history: tuple[IncrementalMaterialUpdate, ...] = ()
    timestamp: float = 0.0
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProjectResumptionPackage:
    """Resumption artifact containing project panorama and agent injection prompt."""

    project_id: str
    current_phase: MilestonePhaseKind
    resumption_prompt: str
    pending_todo_count: int
    ready_todo_ids: tuple[str, ...]
    panorama_summary: str
