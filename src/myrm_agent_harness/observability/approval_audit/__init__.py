"""Auto-Approval Trigger Diagnostics and Dual-Track Quota Attribution Subsystem.

[INPUT]
- types::(ApprovalTriggerCategory, ApprovalTriggerEvent, AutoApprovalAuditReport, DualTrackQuotaBreakdown, TopOffenderItem)
- auditor::AutoApprovalAuditor

[OUTPUT]
- Public exports for auto-approval root cause attribution, Top-Offenders ranking, and dual-track cost transparency

[POS]
Package entry point providing zero-LLM trigger diagnostics and disaggregated quota audit reports.
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
