"""Typed data contracts for the crystallization subsystem.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- CrystallizationLifecycleStage: Lifecycle stages for procedural judgment crystallization.
- RuleLifecycleState: Operational lifecycle state of a crystallized behavioral rule.
- ImportanceScoreResult: Outcome of formation-stage two-factor importance evaluation.
- RuleFeedbackRecord: Feedback telemetry emitted from execution outcomes.
- CrystallizedRuleMetrics: Mutable telemetry tracking rule success, win rate, and lifecycle transitions.

[POS]
Typed data contracts for the crystallization subsystem.
"""

from dataclasses import dataclass, field
from enum import StrEnum


class CrystallizationLifecycleStage(StrEnum):
    """Lifecycle stages for procedural judgment crystallization."""

    FORMATION = "formation"
    APPLICATION = "application"
    REFLECTION = "reflection"


class RuleLifecycleState(StrEnum):
    """Operational lifecycle state of a crystallized behavioral rule."""

    ACTIVE = "active"
    DEGRADED = "degraded"
    RETIRED = "retired"


@dataclass(frozen=True)
class ImportanceScoreResult:
    """Outcome of formation-stage two-factor importance evaluation."""

    confidence: float
    severity: float
    importance: float
    passed_gate: bool
    gate_reason: str


@dataclass(frozen=True)
class RuleFeedbackRecord:
    """Feedback telemetry emitted from execution outcomes."""

    rule_id: str
    session_id: str
    is_success: bool
    secondary_error_occurred: bool
    failure_penalty: float


@dataclass
class CrystallizedRuleMetrics:
    """Mutable telemetry tracking rule success, win rate, and lifecycle transitions."""

    rule_id: str
    facets: list[str] = field(default_factory=lambda: ["global"])
    success_count: int = 0
    fail_count: int = 0
    win_rate: float = 1.0
    state: RuleLifecycleState = RuleLifecycleState.ACTIVE
    weight: float = 1.0
    description: str = ""
