"""Verification protocols and base classes for Goal acceptance criteria.

[INPUT]

[OUTPUT]
- VerificationResult: Dataclass representing the outcome of a single verification criterion.
- AggregatedVerificationResult: Aggregated result preserving per-criterion details.
- BaseCriterion: Abstract base class for all acceptance criteria.

[POS]
Defines the core interfaces for the Goal Acceptance Gatekeeper.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from myrm_agent_harness.agent.goals.protocols import GoalProvider


@dataclass
class VerificationResult:
    """The outcome of evaluating a single acceptance criterion."""

    passed: bool
    criterion_label: str = ""
    reason: str | None = None
    error_logs: str | None = None
    parse_failed: bool = False
    duration_ms: int = 0

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
        return result


@dataclass
class AggregatedVerificationResult:
    """Aggregated verification outcome preserving per-criterion details."""

    passed: bool
    per_criterion: list[VerificationResult] = field(default_factory=list)

    @property
    def failed_count(self) -> int:
        return sum(1 for r in self.per_criterion if not r.passed)

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
