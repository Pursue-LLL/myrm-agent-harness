"""Auto-approval root cause diagnostics and multi-dimensional quota attribution.

[INPUT]
- types::(ApprovalTriggerCategory, ApprovalTriggerEvent, TopOffenderItem, DualTrackQuotaBreakdown, AutoApprovalAuditReport)
- auditor::AutoApprovalAuditor

[OUTPUT]
- AutoApprovalAuditor and approval audit types for server-side security diagnostics and dashboard

[POS]
Harness-level pure-rule auto-approval trigger classification, target normalization,
top offenders ranking, and dual-track quota attribution.
"""

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
