"""
[POS] src/myrm_agent_harness/core/security/auto_review_resolution/types.py
[INPUT] dataclasses, enum, typing
[OUTPUT] DenialReasonCodeEnum, ResolutionBranchEnum, HandoverStatusEnum, DenialDiagnosticPayload, HandoverDeckPayload, ResolutionDecisionRecord, AutoReviewResolutionMetrics

Data structures and specifications for Auto-Review Denial Four-Way Adaptive Resolution State Machine Suite.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class DenialReasonCodeEnum(StrEnum):
    """Normalized diagnostic reason classification for security auto-review block."""

    POLICY_VIOLATION = "POLICY_VIOLATION"
    UNAUTHORIZED_PATH = "UNAUTHORIZED_PATH"
    SENSITIVE_DATA_LEAK = "SENSITIVE_DATA_LEAK"
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    HIGH_RISK_ACTION = "HIGH_RISK_ACTION"
    SANDBOX_ISOLATION_BREACH = "SANDBOX_ISOLATION_BREACH"


class ResolutionBranchEnum(StrEnum):
    """Four-way adaptive resolution strategies inspired by Dots protocol."""

    ASK_USER = "ASK_USER"
    TRY_ALTERNATIVE = "TRY_ALTERNATIVE"
    HANDOVER_TO_USER = "HANDOVER_TO_USER"
    STOP_OPERATION = "STOP_OPERATION"


class HandoverStatusEnum(StrEnum):
    """Lifecycle status for human handover deck."""

    STAGED = "STAGED"
    EXECUTED_BY_USER = "EXECUTED_BY_USER"
    DISMISSED_BY_USER = "DISMISSED_BY_USER"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True)
class DenialDiagnosticPayload:
    """Structured diagnostic report injected back into agent reflection loop when blocked."""

    diagnostic_id: str
    blocked_action: str
    denial_reason: str
    reason_code: DenialReasonCodeEnum
    policy_rule_id: str
    allowed_alternatives: tuple[str, ...]
    suggested_branch: ResolutionBranchEnum
    context_data: dict[str, str] = field(default_factory=dict)
    timestamp: float = 0.0


@dataclass(frozen=True)
class HandoverDeckPayload:
    """Pre-staged contextual execution card handed over to the human user for one-click release."""

    handover_id: str
    session_id: str
    task_description: str
    prepared_command: str
    parameters: dict[str, str]
    guidance_notes: str
    created_at: float
    status: HandoverStatusEnum = HandoverStatusEnum.STAGED
    executed_at: float | None = None


@dataclass(frozen=True)
class ResolutionDecisionRecord:
    """Audit record capturing agent's chosen resolution branch in response to a denial."""

    session_id: str
    diagnostic_id: str
    chosen_branch: ResolutionBranchEnum
    decision_rationale: str
    timestamp: float
    alternative_attempted: str | None = None
    handover_id: str | None = None


@dataclass
class AutoReviewResolutionMetrics:
    """Cumulative telemetry metrics for auto-review denial resolution."""

    total_denials_processed: int = 0
    branch_ask_user_count: int = 0
    branch_alternative_count: int = 0
    branch_handover_count: int = 0
    branch_stop_count: int = 0
    handovers_executed_by_user: int = 0
    handovers_dismissed_by_user: int = 0
