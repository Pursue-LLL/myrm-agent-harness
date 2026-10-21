"""Strongly typed data contracts for autonomous issue resolution pipeline and engineering digests.

Faithfully implements the production invariants benchmarked against Today Huajuan:
- Unattended issue triage and complexity assessment.
- Isolated sandbox branch resolution with automated verification.
- Human-in-the-loop pull request generation (agent proposes, human merges).
- Morning and evening engineering digest compilation.

[OUTPUT]
- IssuePriority: Criticality classification of an issue.
- IssueResolutionStatus: Lifecycle state of autonomous resolution.
- RepositoryIssue: Canonical representation of an issue in a tracked repository.
- FixPlanProposal: Actionable proposal card generated for user selection.
- PullRequestPayload: Structured payload for created pull requests.
- DigestKind: Distinguishes between Morning Brief and Evening Brief.
- EngineeringDigest: Panoramic engineering brief across tracked projects.

[INPUT]
- __future__
- time
- dataclasses
- enum

[OUTPUT]
- IssuePriority
- IssueResolutionStatus
- DigestKind
- RepositoryIssue
- FixPlanProposal
- PullRequestPayload
- EngineeringDigest

[POS]
Strongly typed data contracts for autonomous issue resolution pipeline and engineering digests.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class IssuePriority(StrEnum):
    """Criticality level of a reported repository issue."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class IssueResolutionStatus(StrEnum):
    """Execution lifecycle state for autonomous issue resolution."""

    OPEN = "open"
    ANALYZING = "analyzing"
    IN_SANDBOX_FIX = "in_sandbox_fix"
    TESTING = "testing"
    PR_PENDING_MERGE = "pr_pending_merge"
    MERGED = "merged"
    FAILED = "failed"


class DigestKind(StrEnum):
    """Type of automated engineering briefing."""

    MORNING_BRIEF = "morning_brief"
    EVENING_BRIEF = "evening_brief"


@dataclass(frozen=True)
class RepositoryIssue:
    """Canonical model for a GitHub/GitLab issue to be triaged or resolved."""

    issue_id: int
    repo: str
    title: str
    body: str
    labels: tuple[str, ...] = field(default_factory=tuple)
    priority: IssuePriority = IssuePriority.MEDIUM
    status: IssueResolutionStatus = IssueResolutionStatus.OPEN
    author: str = "user"
    created_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class FixPlanProposal:
    """Actionable resolution plan generated after automated issue analysis."""

    proposal_id: str
    issue_id: int
    repo: str
    target_branch: str
    plan_summary: str
    affected_files: tuple[str, ...]
    estimated_risk: str
    automated_confidence: float  # Range: 0.0 to 1.0


@dataclass(frozen=True)
class PullRequestPayload:
    """Structured artifact generated after successful sandbox verification."""

    pr_id: int
    repo: str
    source_branch: str
    target_branch: str
    title: str
    diff_summary: str
    related_issue_id: int
    automated_review_notes: str
    verification_passed: bool
    created_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class EngineeringDigest:
    """Consolidated engineering overview dispatched in morning and evening."""

    digest_id: str
    kind: DigestKind
    timestamp: float
    projects_monitored: tuple[str, ...]
    pending_merge_prs: tuple[PullRequestPayload, ...]
    resolved_issues: tuple[RepositoryIssue, ...]
    upcoming_tasks: tuple[str, ...]
    open_risks: tuple[str, ...]
