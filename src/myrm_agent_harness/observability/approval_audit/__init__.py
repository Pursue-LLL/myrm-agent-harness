"""Auto-Approval Trigger Diagnostics and Multi-Dimensional Quota Attribution Subsystem.

[INPUT]
- types::(ApprovalTriggerCategory, ApprovalTriggerEvent, AutoApprovalAuditReport, DualTrackQuotaBreakdown, TopOffenderItem)
- auditor::AutoApprovalAuditor

[OUTPUT]
- Public exports for auto-approval trigger classification, dual-track quota attribution, and allowlist recommendations

[POS]
Package entry point providing four-category approval root cause analysis, main-vs-reviewer usage decoupling, and bounded Top-Offenders telemetry.
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
