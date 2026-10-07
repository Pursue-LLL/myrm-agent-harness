"""Context engineering types and data protocols for ReAct trap remediation and ACI design.

Strictly typed data structures without Any, supporting Goldilocks Zone principles,
CoALA structured note taking, and ReAct trap mitigation.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- TrapType: Four canonical ReAct context trap failure modes.
- NoteType: CoALA four-quadrant structured note types.
- ScenarioType: Context engineering profiles for diverse business domains.
- ACISeverity: Severity levels for ACI tool design linting.
- StructuredNote: A persistent structured note offloaded from active context.
- ACIToolParam: Parameter definition for an ACI tool.
- ACIToolContract: Declarative contract for Agent-Computer Interface (ACI) tools.
- ACILintIssue: Lint diagnostic issue for tool contract or prompt structure.
- ACILintReport: Aggregated lint inspection result.
- ContextRemediationConfig: Thresholds and configurations for context engineering remediation.
- ScenarioProfile: Adaptive context configuration tailored to specific domains.
- RemediationResult: Output metrics and transformed messages from remediation pipeline.

[POS]
Context engineering types and data protocols for ReAct trap remediation and ACI design.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class TrapType(StrEnum):
    """Four canonical ReAct context trap failure modes."""

    OBSERVATION_EXPANSION = "observation_expansion"
    RULE_DRIFT = "rule_drift"
    ERROR_CONTAMINATION = "error_contamination"
    THOUGHT_ACCUMULATION = "thought_accumulation"


class NoteType(StrEnum):
    """CoALA four-quadrant structured note types."""

    PROGRESS = "progress"
    DECISION = "decision"
    FINDING = "finding"
    STRATEGY = "strategy"


class ScenarioType(StrEnum):
    """Context engineering profiles for diverse business domains."""

    CUSTOMER_SERVICE = "customer_service"
    GENERAL_OFFICE_CODING = "general_office_coding"
    DEEP_RESEARCH = "deep_research"


class ACISeverity(StrEnum):
    """Severity levels for ACI tool design linting."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class StructuredNote:
    """A persistent structured note offloaded from active context."""

    note_id: str
    note_type: NoteType
    title: str
    content: str
    turn_index: int
    tags: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class ACIToolParam:
    """Parameter definition for an ACI tool."""

    name: str
    type_str: str
    description: str
    required: bool = True


@dataclass(frozen=True)
class ACIToolContract:
    """Declarative contract for Agent-Computer Interface (ACI) tools."""

    name: str
    description: str
    parameters: list[ACIToolParam] = field(default_factory=list)
    tags: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class ACILintIssue:
    """Lint diagnostic issue for tool contract or prompt structure."""

    severity: ACISeverity
    rule_code: str
    target_name: str
    message: str


@dataclass(frozen=True)
class ACILintReport:
    """Aggregated lint inspection result."""

    passed: bool
    issues: list[ACILintIssue] = field(default_factory=list)


@dataclass(frozen=True)
class ContextRemediationConfig:
    """Thresholds and configurations for context engineering remediation."""

    fold_tool_length_threshold: int = 500
    keep_recent_raw_tool_turns: int = 1
    reanchor_turn_interval: int = 10
    max_active_thoughts_turns: int = 3
    enabled_traps: set[TrapType] = field(
        default_factory=lambda: {
            TrapType.OBSERVATION_EXPANSION,
            TrapType.RULE_DRIFT,
            TrapType.ERROR_CONTAMINATION,
            TrapType.THOUGHT_ACCUMULATION,
        }
    )


@dataclass(frozen=True)
class ScenarioProfile:
    """Adaptive context configuration tailored to specific domains."""

    scenario: ScenarioType
    config: ContextRemediationConfig
    core_rules: list[str] = field(default_factory=list)
    max_recent_files: int = 5


@dataclass
class RemediationResult:
    """Output metrics and transformed messages from remediation pipeline."""

    processed_messages: list[dict[str, str]]
    folded_tool_count: int
    pruned_failed_trajectories: int
    reanchored: bool
    decayed_thoughts_count: int
    saved_chars_estimate: int
