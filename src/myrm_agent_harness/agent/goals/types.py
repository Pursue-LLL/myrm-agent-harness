"""Goal engine core types.

[INPUT]

[OUTPUT]
- GoalStatus: Enum for goal lifecycle states.
- GoalBudget: Configuration for goal budget limits.
- Goal: Core data model representing an active objective.
- GoalExecutionSummary: Structured execution summary generated at goal terminal.
- GoalAccountingOutcome: Result of a token/time accounting operation.
- ContinuationDecision: Result of the continuation guard chain evaluation.

[POS]
Defines the core data structures for the goal-based autonomous loop engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal


def _utc_now() -> datetime:
    return datetime.now(UTC)


class GoalStatus(StrEnum):
    """Lifecycle states for a Goal."""

    QUEUED = "queued"
    ACTIVE = "active"
    PAUSED = "paused"
    PENDING_APPROVAL = "pending_approval"
    BUDGET_LIMITED = "budget_limited"
    COMPLETE = "complete"
    CANCELLED = "cancelled"
    NEEDS_HUMAN_REVIEW = "needs_human_review"


@dataclass(frozen=True)
class GoalBudget:
    """Budget limits for a Goal.

    Four dimensions: tokens, USD cost, wall-clock time, and turns.
    """

    max_tokens: int | None = None
    max_usd: float | None = None
    max_time_seconds: int | None = None
    max_turns: int | None = None


@dataclass
class Goal:
    """Core data model representing a long-running objective."""

    goal_id: str
    session_id: str
    objective: str
    status: GoalStatus

    # Short summary for UI display (≤120 chars). Falls back to truncated objective.
    ui_summary: str = ""

    # Queue ordering: lower value = higher priority. Default 0 (FIFO fallback via created_at).
    priority: int = 0

    # When True, GoalInterceptor skips the PENDING_APPROVAL interrupt (used for queued goals).
    auto_approve: bool = False

    # Hard constraints the Agent MUST NOT violate during execution.
    constraints: list[str] = field(default_factory=list)

    # Budget configuration
    budget: GoalBudget | None = None

    # Acceptance Criteria for verification before completion
    acceptance_criteria: list[dict[str, object]] | None = field(default_factory=list)
    subgoals: list[dict[str, object]] | None = field(default_factory=list)
    verification_retries: int = 0

    # Usage tracking
    tokens_used: int = 0
    time_used_seconds: int = 0
    cost_usd: float = 0.0
    turns_used: int = 0

    # Metadata
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)
    metadata: dict[str, object] = field(default_factory=dict)

    @property
    def is_active(self) -> bool:
        return self.status == GoalStatus.ACTIVE

    @property
    def is_terminal(self) -> bool:
        return self.status in (GoalStatus.COMPLETE, GoalStatus.CANCELLED)

    def to_dict(self) -> dict[str, object]:
        """Convert to dictionary for serialization."""
        return {
            "goal_id": self.goal_id,
            "session_id": self.session_id,
            "objective": self.objective,
            "ui_summary": self.ui_summary,
            "priority": self.priority,
            "auto_approve": self.auto_approve,
            "constraints": self.constraints,
            "status": self.status.value,
            "budget": (
                {
                    "max_tokens": self.budget.max_tokens,
                    "max_usd": self.budget.max_usd,
                    "max_time_seconds": self.budget.max_time_seconds,
                    "max_turns": self.budget.max_turns,
                }
                if self.budget
                else None
            ),
            "acceptance_criteria": self.acceptance_criteria,
            "subgoals": self.subgoals,
            "verification_retries": self.verification_retries,
            "tokens_used": self.tokens_used,
            "time_used_seconds": self.time_used_seconds,
            "cost_usd": self.cost_usd,
            "turns_used": self.turns_used,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class GoalExecutionSummary:
    """Structured execution summary generated when a Goal reaches terminal state.

    Assembled from CallRecord + TokenTracker data — no LLM call required.
    """

    files_modified: tuple[str, ...]
    verifications: tuple[dict[str, object], ...]
    browser_checks: int
    total_tokens: int
    total_cost_usd: float
    execution_duration_s: float
    turns_used: int

    def to_dict(self) -> dict[str, object]:
        return {
            "files_modified": list(self.files_modified),
            "verifications": list(self.verifications),
            "browser_checks": self.browser_checks,
            "total_tokens": self.total_tokens,
            "total_cost_usd": round(self.total_cost_usd, 4),
            "execution_duration_s": round(self.execution_duration_s, 1),
            "turns_used": self.turns_used,
        }


@dataclass(frozen=True)
class GoalAccountingOutcome:
    """Result of a token/time accounting operation."""

    goal: Goal
    status_changed: bool
    budget_exhausted: bool


ContinuationVerdict = Literal[
    "continue",
    "done",
    "budget",
    "cancelled",
    "suppressed",
    "steering",
    "no_goal",
]


@dataclass(frozen=True)
class ContinuationDecision:
    """Result of the 7-step continuation guard chain evaluation."""

    should_continue: bool
    verdict: ContinuationVerdict
    reason: str
    turns_used: int | None = None
    max_turns: int | None = None
    message: str = ""
