"""Type contracts for Dual-Track Prior Audit Trail and Compliance Telemetry.

[INPUT]
- None (Standard library dataclasses, enum, datetime, typing)

[OUTPUT]
- PriorAuditState: Lifecycle state of a dual-track audit entry
- ComplianceOutcome: High-level classification (PERMITTED, REFUSED, FAILED)
- AuditTrailEntry: Structured pre-act + post-act paired audit record
- RuleTriggerHit: Aggregated telemetry on security rule / policy triggers
- AuditSummaryStats: Summary metrics for compliance dashboard
- ComplianceReport: Full compliance audit dossier for enterprise inspection

[POS]
Harness-level type definitions and contracts for fail-closed prior audit logging
and zero-leakage compliance observability.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class PriorAuditState(StrEnum):
    """Lifecycle progression state of a dual-track audit record."""

    INTENT_LOGGED = "INTENT_LOGGED"  # Pre-execution intent recorded (fail-closed proof)
    COMPLETED = "COMPLETED"          # Successfully executed post-act paired
    REFUSED = "REFUSED"              # Blocked/denied by policy or human review
    FAILED = "FAILED"                # Failed during execution (exception / timeout)


class ComplianceOutcome(StrEnum):
    """High-level compliance verdict."""

    PERMITTED = "PERMITTED"          # Allowed and completed safely
    REFUSED = "REFUSED"              # Policy or human interception blocked execution
    FAILED = "FAILED"                # Execution crashed or aborted unexpectedly


@dataclass(frozen=True, slots=True)
class AuditTrailEntry:
    """Paired pre-act + post-act structured audit log entry with zero sensitive leakage.

    Attributes:
        entry_id: Unique identifier for the audit record.
        session_id: Associated agent session or task ID.
        agent_id: Identifier of the executing agent or profile.
        tool_name: Name of the invoked tool or subsystem.
        intent_summary: Redacted one-line intent description.
        raw_intent_args: Sanitized/redacted snapshot of proposed arguments.
        rule_name: Security policy or rule name evaluated (e.g. CEL, allowlist, sandbox).
        state: PriorAuditState lifecycle status.
        outcome: High-level ComplianceOutcome.
        is_human_take_the_wheel: Whether this action occurred during human takeover.
        created_at: Pre-execution intent logging timestamp (UTC).
        completed_at: Post-execution completion timestamp (UTC) if reached.
        latency_ms: Total round-trip execution latency in milliseconds.
        output_length: Character length of the sanitized output response.
        error_message: Redacted error description if failed or refused.
        metadata: Additional contextual key-value tags.
    """

    session_id: str
    agent_id: str
    tool_name: str
    intent_summary: str
    entry_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    raw_intent_args: Mapping[str, object] = field(default_factory=dict)
    rule_name: str = "DEFAULT_ALLOW"
    state: PriorAuditState = PriorAuditState.INTENT_LOGGED
    outcome: ComplianceOutcome = ComplianceOutcome.PERMITTED
    is_human_take_the_wheel: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    latency_ms: float = 0.0
    output_length: int = 0
    error_message: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RuleTriggerHit:
    """Aggregated statistics for a specific security rule / policy."""

    rule_name: str
    trigger_count: int
    refused_count: int
    permitted_count: int
    failed_count: int
    refusal_rate: float
    sample_targets: Sequence[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class AuditSummaryStats:
    """Aggregated compliance metrics for dashboard display."""

    total_entries: int
    permitted_count: int
    refused_count: int
    failed_count: int
    human_take_the_wheel_count: int
    compliance_rate: float  # (permitted / total_entries)
    avg_latency_ms: float
    top_rules_triggered: Sequence[RuleTriggerHit] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ComplianceReport:
    """Full structured compliance dossier for enterprise audit and export."""

    report_id: str
    generated_at: str
    time_window_hours: int
    summary: AuditSummaryStats
    entries: Sequence[AuditTrailEntry]
    export_redaction_fingerprint: str
