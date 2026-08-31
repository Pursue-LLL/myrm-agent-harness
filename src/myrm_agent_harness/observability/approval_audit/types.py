"""Auto-Approval Trigger Diagnostics and Multi-Dimensional Quota Attribution Contracts.

[INPUT]
- None (Standard library dataclasses, enum, typing, datetime)

[OUTPUT]
- ApprovalTriggerCategory: Standard 4-category classification enum for approval triggers
- ApprovalTriggerEvent: Immutable telemetry event capturing a single auto-review intercept
- TopOffenderItem: Aggregated high-frequency trigger target with auto-generated allowlist pattern
- DualTrackQuotaBreakdown: Decoupled accounting separating main task vs security audit usage
- AutoApprovalAuditReport: Comprehensive session or window diagnostic audit report

[POS]
Harness-level type system for auto-approval trigger root-cause attribution and dual-track cost transparency.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Mapping


class ApprovalTriggerCategory(StrEnum):
    """Standardized root-cause category of an auto-approval / auto-review intercept."""

    FILE_BOUNDARY = "FILE_BOUNDARY"          # Out-of-workspace file writes / reads
    NETWORK_DOMAIN = "NETWORK_DOMAIN"        # External non-whitelisted HTTP/domain access
    COMMAND_EXECUTION = "COMMAND_EXECUTION"  # Elevated shell commands / scripts
    TOOL_ELEVATION = "TOOL_ELEVATION"        # High-privilege / destructive tool / MCP invocation
    UNKNOWN = "UNKNOWN"                      # Unclassified / generic fallback


@dataclass(frozen=True, slots=True)
class ApprovalTriggerEvent:
    """Immutable single approval intercept event with token & cost footprint.

    Attributes:
        trigger_id: Unique event identifier.
        session_id: Session where intercept occurred.
        category: ApprovalTriggerCategory classification.
        raw_target: Raw parameter string (e.g. full path, url, command line).
        normalized_target: Normalized group key (e.g. domain host, parent directory, command basename).
        tool_name: Offending tool name (e.g. 'shell_exec', 'web_fetch').
        prompt_tokens: Prompt tokens incurred by the review turn.
        completion_tokens: Output tokens incurred by the review turn.
        cost_usd: Estimated financial cost of the review turn.
        occurred_at: Timestamp of detection.
    """

    session_id: str
    category: ApprovalTriggerCategory
    raw_target: str
    normalized_target: str
    tool_name: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    trigger_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def total_tokens(self) -> int:
        """Total tokens incurred by this approval event."""
        return self.prompt_tokens + self.completion_tokens


@dataclass(frozen=True, slots=True)
class TopOffenderItem:
    """Aggregated high-frequency permission boundary offender.

    Attributes:
        normalized_target: Clustered target identifier (e.g. 'api.github.com', '/tmp/*').
        category: Associated ApprovalTriggerCategory.
        hit_count: Number of times this target triggered auto-approval.
        total_tokens: Cumulative tokens consumed by auditing this target.
        estimated_cost_usd: Cumulative financial cost for auditing this target.
        suggested_allow_pattern: Actionable Glob/Pattern for 1-click allowlisting.
    """

    normalized_target: str
    category: ApprovalTriggerCategory
    hit_count: int
    total_tokens: int
    estimated_cost_usd: float
    suggested_allow_pattern: str


@dataclass(frozen=True, slots=True)
class DualTrackQuotaBreakdown:
    """Decoupled usage accounting between main task reasoning and security auto-review."""

    main_task_rounds: int
    main_task_tokens: int
    main_task_cost_usd: float
    audit_rounds: int
    audit_tokens: int
    audit_cost_usd: float

    @property
    def total_rounds(self) -> int:
        """Total execution rounds across main task and audit."""
        return self.main_task_rounds + self.audit_rounds

    @property
    def total_tokens(self) -> int:
        """Total tokens across main task and audit."""
        return self.main_task_tokens + self.audit_tokens

    @property
    def total_cost_usd(self) -> float:
        """Total cost in USD across main task and audit."""
        return round(self.main_task_cost_usd + self.audit_cost_usd, 6)

    @property
    def audit_cost_ratio(self) -> float:
        """Percentage ratio of audit cost relative to total cost (0.0 to 1.0)."""
        if self.total_cost_usd <= 0.0:
            return 0.0
        return min(1.0, round(self.audit_cost_usd / self.total_cost_usd, 4))


@dataclass(frozen=True, slots=True)
class AutoApprovalAuditReport:
    """Comprehensive diagnostic and attribution report for auto-approval events.

    Attributes:
        session_id: Target session identifier.
        total_triggers: Total number of intercepted approval events.
        category_counts: Intercept count breakdown by ApprovalTriggerCategory.
        dual_track_breakdown: Dual-track token and cost attribution.
        top_offenders: Top N aggregated offenders with 1-click whitelist recommendations.
        recommendations: Actionable remediation suggestions.
    """

    session_id: str
    total_triggers: int
    category_counts: Mapping[ApprovalTriggerCategory, int]
    dual_track_breakdown: DualTrackQuotaBreakdown
    top_offenders: list[TopOffenderItem] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
