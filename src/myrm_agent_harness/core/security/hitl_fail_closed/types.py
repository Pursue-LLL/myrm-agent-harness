"""Domain types and models for HITL Approval Fail-Closed Safety Gate & Non-Bypassable Guard.

[INPUT]
- None.

[OUTPUT]
- Typed dataclasses and enums representing approval decisions, fail-closed triggers,
  secondary guard verdicts, and pipeline execution evaluation results.

[POS]
- Harness core security domain models ensuring human-in-the-loop approvals strictly
  default to REJECTED on disconnection/timeout and invariant guards cannot be bypassed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ApprovalDecision(StrEnum):
    """Outcome of the human-in-the-loop approval phase."""

    APPROVED = "APPROVED"
    REJECTED_USER = "REJECTED_USER"
    REJECTED_FAIL_CLOSED = "REJECTED_FAIL_CLOSED"


class FailClosedReason(StrEnum):
    """Reason triggering a fail-closed rejection."""

    NONE = "NONE"
    TIMEOUT = "TIMEOUT"
    CHANNEL_DISCONNECTED = "CHANNEL_DISCONNECTED"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    TRANSPORT_ERROR = "TRANSPORT_ERROR"


class SecondaryGuardVerdict(StrEnum):
    """Invariant validation result evaluated after human approval."""

    PASSED = "PASSED"
    BLOCKED_PHYSICAL_INVARIANT = "BLOCKED_PHYSICAL_INVARIANT"
    BLOCKED_HIGH_RISK_PATTERN = "BLOCKED_HIGH_RISK_PATTERN"


@dataclass(frozen=True)
class ApprovalRequestPayload:
    """Approval request specification presented to the human reviewer."""

    request_id: str
    tool_name: str
    arguments: dict[str, str] = field(default_factory=dict)
    timeout_seconds: float = 30.0
    risk_summary: str = ""


@dataclass(frozen=True)
class HitlExecutionPipelineVerdict:
    """Final decision determined by the two-phase pipeline (Approval + Invariant Guard)."""

    tool_name: str
    arguments: dict[str, str]
    approval_decision: ApprovalDecision
    fail_closed_reason: FailClosedReason
    guard_verdict: SecondaryGuardVerdict
    is_execution_permitted: bool
    audit_id: str
    audit_rationale: str


class HitlFailClosedError(Exception):
    """Raised when an operation is blocked due to HITL approval fail-closed enforcement."""


class SecondaryGuardViolationError(Exception):
    """Raised when an approved operation violates non-bypassable secondary invariant guards."""
