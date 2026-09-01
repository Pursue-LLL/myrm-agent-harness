# observability/approval_audit/

## Overview
Auto-approval trigger root-cause attribution, Top-Offenders clustering, and dual-track quota disaggregation. Categorizes safety approval interventions into 4 standard categories (file boundary, network, shell command, tool elevation) and provides disaggregated cost reports.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Re-exports AutoApprovalAuditor, ApprovalTriggerCategory, and audit report contracts. | ✅ |
| `types.py` | Core | Foundation type contracts: ApprovalTriggerCategory, ApprovalTriggerEvent, DualTrackQuotaBreakdown, TopOffenderItem, AutoApprovalAuditReport. | ✅ |
| `auditor.py` | Core | AutoApprovalAuditor providing pure-rule normalization, bounded top-offender clustering, and disaggregated report generation. | ✅ |

## Key Dependencies

- `observability/economics` (complementary token cost concepts)
- `agent/security` (upstream source of approval events)
