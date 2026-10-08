"""
[POS] src/myrm_agent_harness/core/security/auto_review_resolution/diagnostic_reporter.py
[INPUT] time, uuid, typing, .types (DenialDiagnosticPayload, DenialReasonCodeEnum, ResolutionBranchEnum)
[OUTPUT] DenialDiagnosticReporter

Synthesizes structured, LLM-reflective Denial Diagnostic Payloads with actionable
context, allowed security alternatives, and recommended resolution branches.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import time
import uuid

from .types import (
    DenialDiagnosticPayload,
    DenialReasonCodeEnum,
    ResolutionBranchEnum,
)


class DenialDiagnosticReporter:
    """Produces structured diagnostic reports when security auto-review blocks an action."""

    @classmethod
    def generate_diagnostic(
        cls,
        blocked_action: str,
        denial_reason: str,
        reason_code: DenialReasonCodeEnum,
        policy_rule_id: str,
        context_data: dict[str, str] | None = None,
        custom_alternatives: list[str] | None = None,
        custom_suggested_branch: ResolutionBranchEnum | None = None,
    ) -> DenialDiagnosticPayload:
        """Construct structured DenialDiagnosticPayload for agent reflection loop."""
        diag_id = f"diag-{uuid.uuid4().hex[:12]}"
        now = time.time()
        ctx = context_data.copy() if context_data else {}

        # Derive alternatives if not explicitly provided
        if custom_alternatives is not None:
            alternatives = tuple(custom_alternatives)
        else:
            alternatives = cls._infer_allowed_alternatives(blocked_action, reason_code)

        # Derive suggested resolution branch
        if custom_suggested_branch is not None:
            branch = custom_suggested_branch
        else:
            branch = cls._infer_suggested_branch(reason_code, alternatives)

        return DenialDiagnosticPayload(
            diagnostic_id=diag_id,
            blocked_action=blocked_action,
            denial_reason=denial_reason,
            reason_code=reason_code,
            policy_rule_id=policy_rule_id,
            allowed_alternatives=alternatives,
            suggested_branch=branch,
            context_data=ctx,
            timestamp=now,
        )

    @classmethod
    def _infer_allowed_alternatives(
        cls, blocked_action: str, reason_code: DenialReasonCodeEnum
    ) -> tuple[str, ...]:
        """Infer viable lower-privilege alternative actions."""
        if reason_code == DenialReasonCodeEnum.UNAUTHORIZED_PATH:
            return (
                "read-only file inspection via file_read",
                "create patch file in workspace instead of system directory",
                "ask user for elevated path grant",
            )
        if reason_code == DenialReasonCodeEnum.HIGH_RISK_ACTION:
            return (
                "generate staged dry-run diff preview",
                "handover execution to human operator",
                "execute in isolated ephemeral branch sandbox",
            )
        if reason_code == DenialReasonCodeEnum.RATE_LIMIT_EXCEEDED:
            return (
                "exponential backoff retry",
                "batch operation requests",
                "ask user to relax velocity throttle",
            )
        if reason_code == DenialReasonCodeEnum.SENSITIVE_DATA_LEAK:
            return (
                "apply local PII token redaction",
                "replace credentials with short-lived session ticket",
            )
        if reason_code == DenialReasonCodeEnum.SANDBOX_ISOLATION_BREACH:
            return ("halt immediately and report isolation incident",)
        return ("inspect system status", "request human guidance")

    @classmethod
    def _infer_suggested_branch(
        cls, reason_code: DenialReasonCodeEnum, alternatives: tuple[str, ...]
    ) -> ResolutionBranchEnum:
        """Infer most resilient adaptive resolution branch."""
        if reason_code == DenialReasonCodeEnum.SANDBOX_ISOLATION_BREACH:
            return ResolutionBranchEnum.STOP_OPERATION
        if reason_code == DenialReasonCodeEnum.HIGH_RISK_ACTION:
            return ResolutionBranchEnum.HANDOVER_TO_USER
        if alternatives:
            return ResolutionBranchEnum.TRY_ALTERNATIVE
        return ResolutionBranchEnum.ASK_USER
