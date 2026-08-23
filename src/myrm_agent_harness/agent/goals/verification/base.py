"""Verification protocols and base classes for Goal acceptance criteria.

[INPUT]

[OUTPUT]
- ReviewSeverity: Enum for verification comment severity levels (CRITICAL, WARNING, INFO).
- ReviewComment: Dataclass representing a structured review comment thread item.
- VerificationResult: Dataclass representing the outcome of a single verification criterion.
- AggregatedVerificationResult: Aggregated result preserving per-criterion details.
- BaseCriterion: Abstract base class for all acceptance criteria.

[POS]
Defines the core interfaces for the Goal Acceptance Gatekeeper and review comment SSOT.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from myrm_agent_harness.agent.goals.protocols import GoalProvider


class ReviewSeverity(str, Enum):
    """Severity tier for verification review comments."""

    CRITICAL = "critical"  # Blocking failure: test crash, syntax error, missing required outcome
    WARNING = "warning"    # Non-blocking issue: code smell, suboptimal implementation
    INFO = "info"          # Observational feedback: styling hint, optional suggestion


@dataclass(slots=True)
class ReviewComment:
    """A structured review feedback item linked to a verification criterion or artifact."""

    message: str
    severity: ReviewSeverity = ReviewSeverity.CRITICAL
    target_path: str | None = None
    line_range: str | None = None
    fix_suggestion: str | None = None
    id: str | None = None

    def to_dict(self) -> dict[str, object]:
        """Serialize review comment for metadata persistence and SSE transport."""
        result: dict[str, object] = {
            "message": self.message,
            "severity": self.severity.value if isinstance(self.severity, ReviewSeverity) else str(self.severity),
        }
        if self.target_path:
            result["target_path"] = self.target_path
        if self.line_range:
            result["line_range"] = self.line_range
        if self.fix_suggestion:
            result["fix_suggestion"] = self.fix_suggestion
        if self.id:
            result["id"] = self.id
        return result

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> ReviewComment:
        """Construct a ReviewComment from a dictionary."""
        raw_sev = str(data.get("severity", "critical")).lower()
        severity = ReviewSeverity.CRITICAL
        for item in ReviewSeverity:
            if item.value == raw_sev:
                severity = item
                break

        return cls(
            message=str(data.get("message", "")),
            severity=severity,
            target_path=str(data["target_path"]) if data.get("target_path") else None,
            line_range=str(data["line_range"]) if data.get("line_range") else None,
            fix_suggestion=str(data["fix_suggestion"]) if data.get("fix_suggestion") else None,
            id=str(data["id"]) if data.get("id") else None,
        )


@dataclass
class VerificationResult:
    """The outcome of evaluating a single acceptance criterion."""

    passed: bool
    criterion_label: str = ""
    reason: str | None = None
    error_logs: str | None = None
    parse_failed: bool = False
    wait: bool = False
    duration_ms: int = 0
    comments: list[ReviewComment] = field(default_factory=list)

    @property
    def critical_count(self) -> int:
        return sum(1 for c in self.comments if c.severity == ReviewSeverity.CRITICAL)

    @property
    def warning_count(self) -> int:
        return sum(1 for c in self.comments if c.severity == ReviewSeverity.WARNING)

    @property
    def info_count(self) -> int:
        return sum(1 for c in self.comments if c.severity == ReviewSeverity.INFO)

    def to_dict(self) -> dict[str, object]:
        """Serialize for metadata storage and SSE transport."""
        result: dict[str, object] = {
            "label": self.criterion_label,
            "passed": self.passed,
            "duration_ms": self.duration_ms,
        }
        if self.reason:
            result["reason"] = self.reason
        if self.error_logs:
            result["error_logs"] = self.error_logs
        if self.comments:
            result["comments"] = [c.to_dict() for c in self.comments]
        return result


@dataclass
class AggregatedVerificationResult:
    """Aggregated verification outcome preserving per-criterion details."""

    passed: bool
    per_criterion: list[VerificationResult] = field(default_factory=list)

    @property
    def failed_count(self) -> int:
        return sum(1 for r in self.per_criterion if not r.passed)

    @property
    def all_comments(self) -> list[ReviewComment]:
        """Flatten all review comments across criteria."""
        out: list[ReviewComment] = []
        for r in self.per_criterion:
            out.extend(r.comments)
        return out

    def to_dicts(self) -> list[dict[str, object]]:
        """Serialize all per-criterion results for metadata storage."""
        return [r.to_dict() for r in self.per_criterion]


class BaseCriterion(ABC):
    """Abstract base class for goal acceptance criteria."""

    def __init__(self, **kwargs: Any) -> None:
        self.config = kwargs

    @abstractmethod
    async def verify(self, goal_provider: GoalProvider | None = None) -> VerificationResult:
        """Execute the verification logic.

        Args:
            goal_provider: Optional reference to the GoalProvider to delegate evaluations.

        Returns:
            VerificationResult indicating success or failure with details.
        """
        ...

    @classmethod
    @abstractmethod
    def from_dict(cls, data: dict[str, object]) -> BaseCriterion:
        """Create a criterion instance from a dictionary configuration."""
        ...
