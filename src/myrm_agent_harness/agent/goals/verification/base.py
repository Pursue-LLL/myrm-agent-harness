"""Verification protocols and base classes for Goal acceptance criteria.

[INPUT]

[OUTPUT]
- VerificationResult: Dataclass representing the outcome of a single verification criterion.
- BaseCriterion: Abstract base class for all acceptance criteria.

[POS]
Defines the core interfaces for the Goal Acceptance Gatekeeper.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from myrm_agent_harness.agent.goals.protocols import GoalProvider


@dataclass
class VerificationResult:
    """The outcome of evaluating a single acceptance criterion."""

    passed: bool
    reason: str | None = None
    error_logs: str | None = None


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
