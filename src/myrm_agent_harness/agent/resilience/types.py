"""Marathon error self-correction types.

[INPUT]
- dataclasses: dataclass, field
- enum: StrEnum

[OUTPUT]
- RecoveryActionType: Enumeration of recovery actions (RETRY, ALTERNATIVE_TOOL, SANITIZE_INPUT, ENV_REPAIR, ESCALATE)
- DiagnosticHypothesis: Generated diagnostic hypothesis with root cause analysis and suggested fix
- ErrorCorrectionOutcome: Structured outcome of a self-correction attempt

[POS]
Domain models and types for harness error self-correction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class RecoveryActionType(StrEnum):
    """Action type to resolve execution failure."""

    RETRY = "retry"
    ALTERNATIVE_TOOL = "alternative_tool"
    SANITIZE_INPUT = "sanitize_input"
    ENV_REPAIR = "env_repair"
    ESCALATE = "escalate"


@dataclass(slots=True)
class DiagnosticHypothesis:
    """Hypothesis regarding why an error occurred and how to heal."""

    hypothesis_id: str
    error_summary: str
    root_cause_guess: str
    action_type: RecoveryActionType
    suggested_fix: dict[str, str | int | float | bool] = field(default_factory=dict)
    confidence_score: float = 0.8
    reasoning: str = ""


@dataclass(slots=True)
class ErrorCorrectionOutcome:
    """Outcome of an error self-correction attempt."""

    success: bool
    action_taken: RecoveryActionType
    original_error: str
    diagnostic_details: str
    attempts_made: int
    repaired_output: str | int | float | bool | dict[str, str] | None = None
    fallback_message: str | None = None
