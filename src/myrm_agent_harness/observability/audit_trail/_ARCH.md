# observability/audit_trail/

## Overview
Dual-track prior audit log attribution and compliance trail pack. Enforces fail-closed pre-act intent logging before action execution, pairs post-act results and latency, computes rule trigger telemetry with Take-The-Wheel human intervention tracking, and exports zero-leakage redacted audit dossiers (JSON/CSV/Markdown).

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Re-exports DualTrackAuditCollector, ComplianceTrailExporter, and types. | ✅ |
| `types.py` | Core | Foundation type contracts: PriorAuditState, ComplianceOutcome, AuditTrailEntry, RuleTriggerHit, AuditSummaryStats, ComplianceReport. | ✅ |
| `redactor.py` | Core | Zero-leakage credential scrubber replacing secrets with length and hash fingerprints. | ✅ |
| `collector.py` | Core | Thread-safe in-memory dual-track audit trail collector (log_intent -> complete_act / refuse_act). | ✅ |
| `exporter.py` | Core | ComplianceTrailExporter formatting structured JSON, CSV, and Markdown dossiers. | ✅ |

## Key Dependencies

- `core/security/audit.py` (SecurityDecision integration)
- `observability/metrics` (policy denial telemetry)
