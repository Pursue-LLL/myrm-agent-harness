"""Pipeline Integrity Types and Diagnostic Models.

Defines schemas and enums for inspecting subagent handoff gaps,
enforcing approval gates, validating publish format artifacts,
and checking pre-delivery verification integrity.

[INPUT]
- __future__
- dataclasses
- enum

[OUTPUT]
- GapCategory
- GapSeverity
- StepStage
- HandoffMetadata
- HandoffStep
- HandoffGapDiagnostic
- DecisionChainLink
- PipelineDefinition
- PipelineIntegrityDoctorReport

[POS]
Pipeline Integrity Types and Diagnostic Models.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class GapCategory(StrEnum):
    """Categorization of pipeline handoff and integrity gaps."""

    MISSING_HANDOFF_METADATA = "missing_handoff_metadata"
    MISSING_APPROVAL_GATE = "missing_approval_gate"
    MISSING_PUBLISH_ARTIFACT = "missing_publish_artifact"
    MISSING_VERIFICATION_STEP = "missing_verification_step"


class GapSeverity(StrEnum):
    """Severity classification for diagnostics."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class StepStage(StrEnum):
    """Execution stages within a multi-agent pipeline."""

    ROUTING = "routing"
    ANALYSIS = "analysis"
    EXECUTION = "execution"
    REVIEW = "review"
    VERIFICATION = "verification"
    DELIVERY = "delivery"


@dataclass(frozen=True)
class HandoffMetadata:
    """Metadata contract accompanying an inter-agent delegation or handoff."""

    source_agent: str
    target_agent: str
    transfer_reason: str
    context_keys: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class HandoffStep:
    """Specification of an individual step in a multi-agent orchestration pipeline."""

    step_id: str
    stage: StepStage
    agent_role: str
    requires_approval: bool = False
    requires_verification: bool = False
    produced_artifacts: list[str] = field(default_factory=list)
    metadata: HandoffMetadata | None = None


@dataclass(frozen=True)
class HandoffGapDiagnostic:
    """Detailed diagnostic item produced by the Pipeline Integrity Doctor."""

    rule_id: str
    category: GapCategory
    severity: GapSeverity
    step_id: str
    message: str
    suggested_fix: str


@dataclass(frozen=True)
class DecisionChainLink:
    """Transparent, inspectable record of an agent delegation decision."""

    step_id: str
    from_role: str
    to_role: str
    stage: StepStage
    reason: str


@dataclass
class PipelineDefinition:
    """Complete specification of a multi-agent orchestration pipeline."""

    pipeline_id: str
    name: str
    steps: list[HandoffStep] = field(default_factory=list)
    version: str = "1.0.0"


@dataclass
class PipelineIntegrityDoctorReport:
    """Summary report detailing findings from the pipeline integrity analysis."""

    pipeline_id: str
    total_steps: int
    is_healthy: bool
    gaps: list[HandoffGapDiagnostic] = field(default_factory=list)
    decision_chain: list[DecisionChainLink] = field(default_factory=list)
    scanned_at: float = 0.0
