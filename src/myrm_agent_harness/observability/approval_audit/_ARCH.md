# observability/approval_audit/

## Overview

Auto-approval trigger diagnostics and multi-dimensional quota attribution subsystem. Solves the black-box anxiety of auto-review overhead by providing pure-rule four-category root cause classification, decoupling primary task usage from review overhead, and computing bounded Top-Offenders with actionable 1-click allowlist recommendations.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Re-exports AutoApprovalAuditor, ApprovalTriggerCategory, and audit metric types. | ✅ |
| `types.py` | Core | Foundation type contracts: ApprovalTriggerCategory (4 categories), ApprovalTriggerEvent, DualTrackQuotaBreakdown, TopOffenderItem, AutoApprovalAuditReport. | ✅ |
| `auditor.py` | Core | AutoApprovalAuditor implementing target normalization (paths, domains, command executables), bounded Top-Offenders clustering, and dual-track cost aggregation. | ✅ |

## Key Dependencies

- `observability/economics` (optional cost alignment)
