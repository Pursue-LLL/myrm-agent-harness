"""Dual-Track Prior Audit Trail and Compliance Telemetry Package.

[INPUT]
- types::(PriorAuditState, ComplianceOutcome, AuditTrailEntry, RuleTriggerHit, AuditSummaryStats, ComplianceReport)
- redactor::(sanitize_sensitive_data, redact_string, compute_redaction_fingerprint)
- collector::DualTrackAuditCollector
- exporter::ComplianceTrailExporter

[OUTPUT]
- DualTrackAuditCollector, ComplianceTrailExporter, and associated compliance data types

[POS]
Harness-level zero-leakage pre-act intent and post-act result paired audit trail framework.
"""

from myrm_agent_harness.observability.audit_trail.collector import DualTrackAuditCollector
from myrm_agent_harness.observability.audit_trail.exporter import ComplianceTrailExporter
from myrm_agent_harness.observability.audit_trail.redactor import (
    compute_redaction_fingerprint,
    redact_string,
    sanitize_sensitive_data,
)
from myrm_agent_harness.observability.audit_trail.types import (
    AuditSummaryStats,
    AuditTrailEntry,
    ComplianceOutcome,
    ComplianceReport,
    PriorAuditState,
    RuleTriggerHit,
)

__all__ = [
    "AuditSummaryStats",
    "AuditTrailEntry",
    "ComplianceOutcome",
    "ComplianceReport",
    "ComplianceTrailExporter",
    "DualTrackAuditCollector",
    "PriorAuditState",
    "RuleTriggerHit",
    "compute_redaction_fingerprint",
    "redact_string",
    "sanitize_sensitive_data",
]
