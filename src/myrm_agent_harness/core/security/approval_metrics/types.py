"""Data types and schemas for Approval False Positive Metric Loop.

[INPUT]
- None.

[OUTPUT]
- Typed data models and enums for classifier verdicts, human review feedback, and false positive metrics.

[POS]
- Harness core security module enabling empirical false positive rate observability and rule feedback loops.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ClassifierDecision(StrEnum):
    """Possible outcomes from transcript classification."""

    ALLOW = "allow"
    DENY = "deny"
    UNCERTAIN = "uncertain"


class FeedbackOutcome(StrEnum):
    """Human review adjudication and ground truth label."""

    UNREVIEWED = "unreviewed"
    TRUE_POSITIVE = "true_positive"
    FALSE_POSITIVE = "false_positive"
    CONFIRMED_SAFE = "confirmed_safe"


@dataclass(frozen=True)
class ClassifierVerdictLog:
    """Immutable structured record of a classifier decision."""

    audit_id: str
    timestamp: float
    command: str
    decision: ClassifierDecision
    reason: str
    workspace_root: str | None = None
    taint_labels: list[str] = field(default_factory=list)
    feedback: FeedbackOutcome = FeedbackOutcome.UNREVIEWED
    feedback_reason: str | None = None
    reviewed_at: float | None = None


@dataclass(frozen=True)
class FalsePositiveRateMetric:
    """Aggregated empirical metrics across a sliding time window."""

    window_seconds: float
    total_evaluations: int
    total_blocks_or_asks: int
    confirmed_false_positives: int
    confirmed_true_positives: int
    false_positive_rate: float
    alert_threshold: float
    is_alerting: bool


@dataclass(frozen=True)
class FalsePositiveSample:
    """Exported false positive sample for tuning BLOCK rules and ALLOW exceptions."""

    audit_id: str
    timestamp: float
    command: str
    decision: ClassifierDecision
    original_reason: str
    feedback_reason: str
    suggested_rule_tuning: str
