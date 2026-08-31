"""Auto-Approval Trigger Diagnostics and Multi-Dimensional Quota Attribution Subsystem.

[INPUT]
- types::(ApprovalTriggerCategory, ApprovalTriggerEvent, AutoApprovalAuditReport, DualTrackQuotaBreakdown, TopOffenderItem)
- auditor::AutoApprovalAuditor

[OUTPUT]
- Public exports for auto-approval trigger categorization, dual-track quota breakdown, and Top-Offenders attribution

[POS]
Package entry point providing zero-LLM root-cause attribution and dual-track cost transparency for auto-approvals.
"""

from __future__ import annotations

from myrm_agent_harness.observability.approval_audit.auditor import AutoApprovalAuditor
from myrm_agent_harness.observability.approval_audit.types import (
    ApprovalTriggerCategory,
    ApprovalTriggerEvent,
    AutoApprovalAuditReport,
    DualTrackQuotaBreakdown,
    TopOffenderItem,
)

__all__ = [
    "ApprovalTriggerCategory",
    "ApprovalTriggerEvent",
    "AutoApprovalAuditReport",
    "AutoApprovalAuditor",
    "DualTrackQuotaBreakdown",
    "TopOffenderItem",
]
