"""Marathon error self-correction and execution budget types.

[INPUT]
- typing: Any, Optional, Dict, List

[OUTPUT]
- DiagnosticHypothesis: A generated hypothesis and candidate fix.
- RecoveryAction: Action taken by self-correction governor (RETRY, ALTERNATIVE_TOOL, SANITIZE_INPUT, ESCALATE).
- ExecutionBudgetState: State of dynamic execution budget and step quotas.

[POS]
Domain types for error self-correction and execution budget governance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


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
    suggested_fix: dict[str, Any] = field(default_factory=dict)
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
    repaired_output: Any = None
    fallback_message: str | None = None


@dataclass(slots=True)
class ExecutionBudgetConfig:
    """Configuration for execution budget and quota circuit breakers."""

    max_steps_per_task: int = 100
    max_tokens_total: int = 1_000_000
    max_consecutive_errors: int = 3
    max_duration_seconds: float = 14400.0  # 4 hours
    token_rate_warn_threshold: int = 50_000  # tokens per 5-minute window
