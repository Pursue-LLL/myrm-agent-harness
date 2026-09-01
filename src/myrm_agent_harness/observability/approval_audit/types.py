"""Auto-Approval Trigger Diagnostics and Dual-Track Quota Attribution Types.

[INPUT]
- None (Standard library dataclasses, enum, datetime, typing)

[OUTPUT]
- ApprovalTriggerCategory: Standard 4-category classification enum
- ApprovalTriggerEvent: Immutable trigger occurrence record
- TopOffenderItem: Aggregated high-frequency boundary offender with suggested allowlist rule
- DualTrackQuotaBreakdown: Disaggregated usage metrics (main task vs audit agent)
- AutoApprovalAuditReport: Structured session/global diagnostic summary

[POS]
Harness-level type definitions and data contracts for auto-approval trigger root-cause attribution and dual-track cost transparency.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Mapping, Sequence


class ApprovalTriggerCategory(StrEnum):
    """Standard four-category root causes for auto-approval triggers."""

    FILE_BOUNDARY = "FILE_BOUNDARY"  # File write outside authorized workspace
    NETWORK_DOMAIN = "NETWORK_DOMAIN"  # Network/HTTP fetch to non-allowlisted domain
    COMMAND_EXECUTION = "COMMAND_EXECUTION"  # Shell/CLI execution requiring permission
    TOOL_ELEVATION = "TOOL_ELEVATION"  # High-risk MCP or destructive tool call
    UNKNOWN = "UNKNOWN"  # Fallback uncategorized trigger


@dataclass(frozen=True, slots=True)
class ApprovalTriggerEvent:
    """Immutable event capturing an auto-approval / guardrail trigger occurrence.

    Attributes:
        trigger_id: Unique event identifier.
        session_id: Session where the trigger occurred.
        category: ApprovalTriggerCategory classification.
        raw_target: Raw parameter string (e.g. full path, url, shell command).
        normalized_target: Sanitized and clustered target (e.g. directory, domain, command base).
        tool_name: Name of tool being guarded.
        prompt_tokens: Prompt tokens used by the guard/review agent (if any).
        completion_tokens: Output tokens used by the guard/review agent.
        cost_usd: Estimated financial cost incurred by the review step.
        occurred_at: Event timestamp.
    """

    session_id: str
    category: ApprovalTriggerCategory
    raw_target: str
    normalized_target: str
    tool_name: str
    trigger_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def total_tokens(self) -> int:
        """Total tokens consumed by this review event."""
        return self.prompt_tokens + self.completion_tokens


@dataclass(frozen=True, slots=True)
class TopOffenderItem:
    """Aggregated top-frequency boundary violator with actionable allowlist hint.

    Attributes:
        normalized_target: Clustered target identifier (domain, dir prefix, command).
        category: Trigger category.
        hit_count: Number of times this target triggered auto-approval.
        total_tokens: Cumulative tokens consumed by auditing this target.
        estimated_cost_usd: Cumulative financial cost in USD.
        suggested_allow_pattern: Machine-readable glob/prefix pattern for 1-click allowlisting.
    """

    normalized_target: str
    category: ApprovalTriggerCategory
    hit_count: int
    total_tokens: int
    estimated_cost_usd: float
    suggested_allow_pattern: str


@dataclass(frozen=True, slots=True)
class DualTrackQuotaBreakdown:
    """Disaggregated multi-dimensional usage metrics comparing main task vs safety audit."""

    main_task_rounds: int = 0
    main_task_tokens: int = 0
    main_task_cost_usd: float = 0.0
    audit_rounds: int = 0
    audit_tokens: int = 0
    audit_cost_usd: float = 0.0

    @property
    def total_rounds(self) -> int:
        """Total execution rounds across main model and audit agents."""
        return self.main_task_rounds + self.audit_rounds

    @property
    def total_tokens(self) -> int:
        """Total token consumption across main model and audit agents."""
        return self.main_task_tokens + self.audit_tokens

    @property
    def total_cost_usd(self) -> float:
        """Total financial cost in USD."""
        return round(self.main_task_cost_usd + self.audit_cost_usd, 6)

    @property
    def audit_cost_ratio(self) -> float:
        """Percentage of total cost spent on safety auditing (0.0 to 1.0)."""
        if self.total_cost_usd <= 0.0:
            return 0.0
        return min(1.0, round(self.audit_cost_usd / self.total_cost_usd, 4))


@dataclass(frozen=True, slots=True)
class AutoApprovalAuditReport:
    """Comprehensive auto-approval diagnostic report with actionable recommendations."""

    session_id: str
    total_triggers: int
    category_counts: Mapping[str, int]
    dual_track_breakdown: DualTrackQuotaBreakdown
    top_offenders: Sequence[TopOffenderItem]
    recommendations: Sequence[str]
