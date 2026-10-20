"""Strongly-typed DTOs and Enums for Multi-Perspective Subagent Review & Bounded Review Loop (Item 32).

Defines the contracts for Tri-Perspective Reviewers (Correctness, Test Coverage, Simplicity)
and bounded self-healing review rounds.

[INPUT]
- __future__
- dataclasses
- datetime
- enum

[OUTPUT]
- ReviewPerspective
- FindingSeverity
- ReviewLoopStatus
- ReviewFinding
- PerspectiveReviewReport
- LoopRoundRecord
- ReviewLoopResult

[POS]
Strongly-typed DTOs and Enums for Multi-Perspective Subagent Review & Bounded Review Loop (Item 32).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class ReviewPerspective(StrEnum):
    """The three specialized review lenses applied concurrently."""

    CORRECTNESS = "correctness"
    TEST_COVERAGE = "test_coverage"
    SIMPLICITY = "simplicity"


class FindingSeverity(StrEnum):
    """Severity classification for review findings."""

    BLOCKER = "blocker"
    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"
    SUGGESTION = "suggestion"

    @property
    def is_blocking(self) -> bool:
        """Determines if the finding prevents immediate merge/approval."""
        return self in (FindingSeverity.BLOCKER, FindingSeverity.CRITICAL, FindingSeverity.MAJOR)


class ReviewLoopStatus(StrEnum):
    """State progression of a bounded review loop."""

    PENDING = "pending"
    IN_REVIEW = "in_review"
    FIXING = "fixing"
    CONVERGED = "converged"
    MAX_ROUNDS_REACHED = "max_rounds_reached"


@dataclass(frozen=True)
class ReviewFinding:
    """A granular finding discovered by a reviewer under its specific lens."""

    perspective: ReviewPerspective
    severity: FindingSeverity
    file_path: str
    issue: str
    suggestion: str
    line_number: int | None = None


@dataclass(frozen=True)
class PerspectiveReviewReport:
    """Consolidated assessment from a single perspective reviewer."""

    perspective: ReviewPerspective
    reviewer_name: str
    approved: bool
    findings: tuple[ReviewFinding, ...] = field(default_factory=tuple)
    summary: str = ""

    @property
    def blocking_findings(self) -> tuple[ReviewFinding, ...]:
        """Extract findings with blocking severity."""
        return tuple(f for f in self.findings if f.severity.is_blocking)


@dataclass(frozen=True)
class LoopRoundRecord:
    """Audit record of a single review & remediation iteration."""

    round_number: int
    perspective_reports: dict[ReviewPerspective, PerspectiveReviewReport]
    all_findings: tuple[ReviewFinding, ...]
    has_blocking_issues: bool
    fix_description: str | None = None
    converged: bool = False
    timestamp: datetime = field(default_factory=lambda: datetime.now(tz=UTC))


@dataclass(frozen=True)
class ReviewLoopResult:
    """Final outcome of the bounded review loop execution."""

    loop_id: str
    status: ReviewLoopStatus
    total_rounds: int
    max_rounds: int
    rounds: tuple[LoopRoundRecord, ...]
    is_clean: bool
    final_summary: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
