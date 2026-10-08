"""
[POS] src/myrm_agent_harness/core/security/scoped_approval/types.py
[INPUT] dataclasses, enum, typing
[OUTPUT] GrantScope, ActionRiskTier, GateDecision, ApprovalGrantLease, GrantUsageRecord, RiskEvaluationRequest, RiskEvaluationResult, ScopedApprovalMetrics
Domain types for Scoped Approval Grant and Risk-Tiered Gate Suite.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class GrantScope(StrEnum):
    """Five-tier approval grant validity scopes."""

    ONCE = "once"
    TASK = "task"
    SESSION = "session"
    HOURS_24 = "24h"
    ALWAYS = "always"


class ActionRiskTier(StrEnum):
    """Action or tool operational risk classification."""

    READ_ONLY = "read_only"
    LOW_RISK_WRITE = "low_risk_write"
    HIGH_RISK_WRITE = "high_risk_write"
    IRREVERSIBLE_EGRESS = "irreversible_egress"


class GateDecision(StrEnum):
    """Tri-state access control resolution."""

    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


@dataclass(frozen=True)
class ApprovalGrantLease:
    """Scoped execution permission voucher issued by user."""

    grant_id: str
    tool_name: str
    scope: GrantScope
    agent_id: str
    session_id: str
    task_id: str | None = None
    granted_at: float = 0.0
    expires_at: float | None = None
    revoked: bool = False
    use_count: int = 0

    def is_active(
        self, current_time: float, task_id: str | None, session_id: str | None
    ) -> bool:
        """Evaluate if lease remains active and valid for target invocation."""
        if self.revoked:
            return False

        if self.expires_at is not None and current_time > self.expires_at:
            return False

        if self.scope == GrantScope.ONCE and self.use_count >= 1:
            return False

        if self.scope == GrantScope.TASK:
            return bool(self.task_id and task_id and self.task_id == task_id)

        if self.scope == GrantScope.SESSION:
            return bool(session_id and self.session_id == session_id)

        return True


@dataclass(frozen=True)
class GrantUsageRecord:
    """Historical audit trail entry capturing lease usage."""

    record_id: str
    grant_id: str
    tool_name: str
    agent_id: str
    timestamp: float
    task_id: str | None
    session_id: str


@dataclass(frozen=True)
class RiskEvaluationRequest:
    """Execution context evaluated against risk gates and active leases."""

    tool_name: str
    risk_tier: ActionRiskTier
    agent_id: str
    session_id: str
    task_id: str | None = None
    parameters_summary: str = ""


@dataclass(frozen=True)
class RiskEvaluationResult:
    """Resolution of security gate evaluation."""

    decision: GateDecision
    reason: str
    matched_grant_id: str | None = None
    risk_tier: ActionRiskTier = ActionRiskTier.READ_ONLY
    requires_hitl_prompt: bool = False


@dataclass
class ScopedApprovalMetrics:
    """Telemetry counters for scoped grants and tiered gate evaluations."""

    evaluations_total: int = 0
    silent_allows_total: int = 0
    asks_required_total: int = 0
    denials_total: int = 0
    grants_issued_total: int = 0
    grants_revoked_total: int = 0
    grant_redemptions_total: int = 0
