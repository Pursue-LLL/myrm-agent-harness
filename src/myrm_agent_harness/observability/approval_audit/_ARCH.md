# observability/approval_audit/

## Overview
Auto-approval trigger diagnostics and multi-dimensional quota attribution engine. Categorizes security approval triggers into four root-cause buckets (FILE_BOUNDARY, NETWORK_DOMAIN, COMMAND_EXECUTION, TOOL_ELEVATION), ranks top-offender targets with suggested allowlist patterns, and decouples primary model costs from auxiliary auto-review agent costs.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Re-exports AutoApprovalAuditor and approval audit types. | ✅ |
| `types.py` | Core | Foundation type contracts: ApprovalTriggerCategory, ApprovalTriggerEvent, TopOffenderItem, DualTrackQuotaBreakdown, AutoApprovalAuditReport. | ✅ |
| `auditor.py` | Core | AutoApprovalAuditor implementing target normalization, allowlist recommendation, offender clustering, and dual-track quota attribution. | ✅ |

## Key Dependencies

- `core/security/audit.py` (SecurityDecision log integration)
- `observability/metrics` (security metric integration)
