"""Denial message the model reads when the approval middleware refuses a tool call.

[INPUT]
- core.security.auto_review_resolution::DenialDiagnosticReporter, DenialReasonCodeEnum (POS: Derives a denial's allowed alternatives and suggested resolution branch from its reason code.)

[OUTPUT]
- infer_denial_reason_code: classify a denial from its reason text and the tool name
- build_auto_review_denial_message: render the structured denial text (reason code, allowed alternatives, four resolution branches); retains nothing per denial

[POS]
Gives the model something to act on instead of a bare refusal. Used by batch_processor to word the refusals of the read-only lease, the permission engine, the shell-escalation check and the LLM security review.
"""

from __future__ import annotations

from myrm_agent_harness.core.security.auto_review_resolution import (
    DenialDiagnosticReporter,
    DenialReasonCodeEnum,
)


def infer_denial_reason_code(reason: str, tool_name: str) -> DenialReasonCodeEnum:
    """Infer normalized security denial reason code from policy reason text and tool name."""
    lower_reason = reason.lower()
    lower_tool = tool_name.lower()

    if any(k in lower_reason for k in ("path", "directory", "traversal", "unauthorized path")):
        return DenialReasonCodeEnum.UNAUTHORIZED_PATH

    if any(k in lower_reason for k in ("secret", "token", "password", "credential", "leak", "exfiltrat")):
        return DenialReasonCodeEnum.SENSITIVE_DATA_LEAK

    if any(k in lower_reason for k in ("rate limit", "throttle", "velocity", "too many requests")):
        return DenialReasonCodeEnum.RATE_LIMIT_EXCEEDED

    if any(k in lower_reason for k in ("sandbox", "isolation", "escape", "cgroup", "device")):
        return DenialReasonCodeEnum.SANDBOX_ISOLATION_BREACH

    if any(
        k in lower_reason or k in lower_tool
        for k in ("destructive", "irreversible", "rm -rf", "delete", "payment", "money", "drop database")
    ):
        return DenialReasonCodeEnum.HIGH_RISK_ACTION

    return DenialReasonCodeEnum.POLICY_VIOLATION


def build_auto_review_denial_message(tool_name: str, reason: str, hint: str = "") -> str:
    """Synthesize structured denial message with 4-way adaptive resolution guidance.

    Stateless: the diagnostic exists only to render this message, so a long-lived process keeps nothing per denial.
    """
    diag = DenialDiagnosticReporter.generate_diagnostic(
        blocked_action=tool_name,
        denial_reason=reason,
        reason_code=infer_denial_reason_code(reason, tool_name),
        policy_rule_id="SECURITY_AUTO_REVIEW_GATE",
    )

    alternatives_str = "\n".join(f"  - {alt}" for alt in diag.allowed_alternatives)
    message_parts = [
        f"Tool execution denied by security policy: {reason}{hint}",
        "",
        "[SECURITY_DENIAL_DIAGNOSTIC]",
        f"Diagnostic ID: {diag.diagnostic_id}",
        f"Reason Code: {diag.reason_code.value}",
        f"Suggested Branch: {diag.suggested_branch.value}",
        f"Allowed Alternatives:\n{alternatives_str}",
        "",
        "Instruction: You must now adapt by choosing one of the four resolution branches:",
        "1. ASK_USER: Ask the user for explicit authorization or clarification.",
        "2. TRY_ALTERNATIVE: Attempt one of the allowed alternatives above.",
        "3. HANDOVER_TO_USER: Hand this specific operation over to the user for manual confirmation.",
        "4. STOP_OPERATION: Terminate the blocked trajectory safely and report findings to user.",
    ]

    return "\n".join(message_parts)
