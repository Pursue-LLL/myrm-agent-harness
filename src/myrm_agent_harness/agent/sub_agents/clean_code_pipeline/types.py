"""Data types for Clean Code Assembly Pipeline and Architecture Dependency Linter (Item 62).

[INPUT]
- Multi-agent Clean Code assembly task specifications and module dependency AST trees.

[OUTPUT]
- PipelineStage, StageStatus, ViolationType, StageArtifact,
  ArchitectureViolation, DependencyRule, CleanCodeTask, LinterResult.

[POS]
- Core domain types for Item 62 five-stage Clean Code assembly and DIP architecture enforcement.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class PipelineStage(StrEnum):
    """The 5 single-responsibility stages inspired by Uncle Bob & John Ousterhout."""

    SPECIFIER = "specifier"  # Gherkin BDD contract & acceptance criteria
    CODER = "coder"  # Deep module implementation & core unit tests
    CLEANER = "cleaner"  # CRAP complexity reduction, refactoring, smell elimination
    HARDENER = "hardener"  # Mutation testing, boundary & resilience test synthesis
    QA = "qa"  # End-to-end acceptance script verification & sign-off


class StageStatus(StrEnum):
    """Execution lifecycle status of an individual stage or overall pipeline."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


class ViolationType(StrEnum):
    """Classification of architectural layer dependency violations."""

    LAYER_BYPASS = "layer_bypass"
    INVERTED_DEPENDENCY = "inverted_dependency"
    CIRCULAR_DEPENDENCY = "circular_dependency"


@dataclass(slots=True)
class StageArtifact:
    """Artifact produced by a specific pipeline stage and passed forward."""

    stage: PipelineStage
    title: str
    content: str
    metadata: dict[str, str] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


@dataclass(slots=True)
class ArchitectureViolation:
    """Detailed evidence of an architectural boundary or layer constraint breach."""

    source_module: str
    target_module: str
    violation_type: ViolationType
    rule_description: str
    remediation_suggestion: str  # Actionable DIP refactoring guidance


@dataclass(slots=True)
class DependencyRule:
    """Specification of permitted unidirectional dependencies between layers."""

    source_layer: str
    allowed_target_layers: list[str]


@dataclass(slots=True)
class CleanCodeTask:
    """Full state representing an in-flight 5-stage Clean Code pipeline run."""

    task_id: str
    title: str
    spec_prompt: str
    current_stage: PipelineStage = PipelineStage.SPECIFIER
    status: StageStatus = StageStatus.PENDING
    artifacts: dict[str, StageArtifact] = field(default_factory=dict)
    stage_history: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


@dataclass(slots=True)
class LinterResult:
    """Outcome of static architectural dependency linting across modules."""

    is_valid: bool
    violations: list[ArchitectureViolation] = field(default_factory=list)
    scanned_files_count: int = 0
    dependency_edges: list[tuple[str, str]] = field(default_factory=list)
