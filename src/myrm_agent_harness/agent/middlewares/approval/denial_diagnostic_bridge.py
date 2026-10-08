"""Denial Diagnostic Bridge connecting security auto-review denials to 4-way adaptive resolution.

[INPUT]
- Tool name, invocation arguments, security denial reason, session identifier, and optional hints.

[OUTPUT]
- Structured, LLM-reflective denial diagnostic message embedding reason codes,
  allowed alternatives, and Dots-style 4-way adaptive resolution guidance.

[POS]
- Harness approval middleware in agent/middlewares/approval/denial_diagnostic_bridge.py.
"""

from __future__ import annotations

import json

from myrm_agent_harness.core.security.auto_review_resolution import (
    DenialReasonCodeEnum,
    ResolutionBranchEnum,
    get_auto_review_resolution_facade,
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


def build_auto_review_denial_message(
    tool_name: str,
    args: dict[str, object] | None,
    reason: str,
    session_key: str,
    hint: str = "",
) -> str:
    """Synthesize structured denial message with 4-way adaptive resolution guidance."""
    # Summarize tool action
    args_summary = ""
    if args:
        try:
            args_summary = json.dumps(args, ensure_ascii=False, default=str)
            if len(args_summary) > 200:
                args_summary = args_summary[:200] + "..."
        except Exception:
            args_summary = str(args)[:200]

    blocked_action = f"{tool_name}({args_summary})" if args_summary else tool_name
    reason_code = infer_denial_reason_code(reason, tool_name)
    facade = get_auto_review_resolution_facade()

    # Register structured denial in session state machine
    context_data = {"tool_name": tool_name}
    if args_summary:
        context_data["args_summary"] = args_summary

    diag = facade.report_and_register_denial(
        session_id=session_key,
        blocked_action=blocked_action,
        denial_reason=reason,
        reason_code=reason_code,
        policy_rule_id="SECURITY_AUTO_REVIEW_GATE",
        context_data=context_data,
    )

    # If suggested branch is HANDOVER_TO_USER, pre-stage a handover deck card
    if diag.suggested_branch == ResolutionBranchEnum.HANDOVER_TO_USER:
        param_dict = {str(k): str(v) for k, v in (args or {}).items()}
        facade.stage_handover_deck(
            session_id=session_key,
            task_description=f"Action blocked: {blocked_action}",
            prepared_command=tool_name,
            parameters=param_dict,
            guidance_notes=f"Security auto-review blocked this action ({reason}). You may manually review and execute.",
        )

    # Format structured message for agent reflection
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
