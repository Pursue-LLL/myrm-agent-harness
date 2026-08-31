# observability/approval_audit/

## Overview
Auto-approval trigger diagnostics and multi-dimensional quota attribution subsystem.
Categorizes intercepts into four standard root causes (FILE_BOUNDARY, NETWORK_DOMAIN, COMMAND_EXECUTION, TOOL_ELEVATION), computes dual-track usage separation (main task vs security review), aggregates high-frequency offenders with bounded memory, and generates actionable 1-click whitelist recommendations.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Re-exports AutoApprovalAuditor, ApprovalTriggerCategory, and audit report types. | ✅ |
| `types.py` | Core | Foundation type system: ApprovalTriggerCategory, ApprovalTriggerEvent, DualTrackQuotaBreakdown, TopOffenderItem, AutoApprovalAuditReport. | ✅ |
| `auditor.py` | Core | AutoApprovalAuditor pure-rule categorization, target normalization, bounded Top-Offenders aggregation, and dual-track report generator. | ✅ |

## Key Dependencies

- `observability/metrics` (optional metric exposure)
