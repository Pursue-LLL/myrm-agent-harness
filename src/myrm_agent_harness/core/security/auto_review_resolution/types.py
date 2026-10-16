"""
[POS] src/myrm_agent_harness/core/security/auto_review_resolution/types.py
[INPUT] dataclasses, enum, typing
[OUTPUT] DenialReasonCodeEnum, ResolutionBranchEnum, DenialDiagnosticPayload

Data structures for the Auto-Review Denial diagnostic and its four adaptive resolution branches.
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
