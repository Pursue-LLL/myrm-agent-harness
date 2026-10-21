"""Audit Trail — structured decision log for tool-call security.

Records every security decision made during an Agent session into a
ContextVar accumulator. The log can be retrieved at the end of a run
(e.g. for Cron metadata) or inspected for debugging.

[INPUT]
- (none — self-contained, pure standard library)

[OUTPUT]
- DecisionKind: the closed set of decision names an audit entry can carry
- SecurityDecision: a single audit entry
- is_blocking_decision(): whether a decision stopped the action it was about
- is_policy_denial(): whether a decision name counts as a policy denial in telemetry
- record_decision(): append a decision to the current session log
- get_audit_entries(): retrieve all entries for the current session
- reset_audit_log(): clear the log (call at the start of each Agent run)

[POS]
Cross-cutting concern. Called from tool_interceptor_middleware and all
security guard modules at every decision point.
"""

from __future__ import annotations

import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Literal

DecisionKind = Literal[
    "ALLOW",
    "DENY",
    "ASK",
    "ALLOWLIST_ALLOW",
    "ALLOWLIST_AUTO_APPROVE",
    "CRON_DENY",
    "TAINT_ESCALATE",
    "USER_APPROVED",
    "USER_EDITED",
    "USER_REJECTED",
    "USER_DENIED",
    "TIMEOUT_DENIED",
    "TIMEOUT_APPROVED",
    "LOOP_WARN",
    "LOOP_BREAK",
    "ESTOP_BLOCKED",
    "CONTEXT_TRUNCATED",
    "CONTEXT_PERSISTED",
    "SKILL_HOOK_BLOCK",
    "SKILL_HOOK_APPROVAL",
    "SSRF_BLOCKED",
    "SCAN_FINDING",
    "PII_DETECTED",
    "PII_REDACTED",
    "PII_BLOCKED",
    "PII_BLOCKED_REDACTED",
    "PII_PSEUDONYMIZED",
    "MESSAGE_FILTERED",
    "MESSAGE_ALLOWED",
    "CREDENTIAL_LEAK_DETECTED",
    "CREDENTIAL_LEAK_BLOCKED",
    "YOLO_AUTO_APPROVE",
    "DOMAIN_RUNTIME_ALLOW",
    "DOMAIN_APPROVED",
    "SUBAGENT_AUTO_DENY",
    "LLM_REVIEW_ALLOW",
    "LLM_REVIEW_DENY",
    "LLM_REVIEW_UNCERTAIN",
    "HOOK_BLOCKED",
    "POST_HOOK_BLOCKED",
    "FREQUENCY_WARN",
    "FREQUENCY_BREAK",
    "TURN_BUDGET_BREAK",
    "SANDBOX_BOUNDARY_ESCALATE",
    "CANARY_LEAKED",
    "INJECTION_DETECTED",
    "INJECTION_BLOCKED",
    "DANGEROUS_INTENT_DETECTED",
    "DANGEROUS_INTENT_BLOCKED",
    "MAP_ALLOWLIST_SKIPPED",
    "MISSING_SEMANTICS_BLOCKED",
    "MISSING_SEMANTICS_FALLBACK",
    "REDIRECT_HEADER_STRIPPED",
    "INSECURE_REDIRECT_BLOCKED",
    "BATCH_RISK_DUAL_INSURANCE_ESCALATED",
    "BATCH_SIZE_LIMIT_EXCEEDED",
    "SANDBOX_AUTO_BYPASS",
    "ALLOWLIST_SESSION_ALLOW",
    "PROTECTED_INSTRUCTION_ATTEMPT",
    "PROTECTED_INSTRUCTION_ALLOWLIST_BLOCKED",
    "FINANCIAL_GATE_ALLOWLIST_BLOCKED",
    "IRREVERSIBLE_ACTION_ALLOWLIST_BLOCKED",
    "NO_CONTEXT_DENIED",
    "PRIVACY_ROUTE",
    # Approval batch: untrusted-ingress fence, YOLO gates, outbound and shell escalation checks, auto mode
    "INGRESS_FENCE_DENY",
    "INGRESS_FENCE_YOLO_BLOCKED",
    "OPERATOR_AS_KEY_DENY",
    "READONLY_RESEARCH_LEASE_BLOCKED",
    "YOLO_DENY_OVERRIDE",
    "YOLO_FINANCIAL_GATE_BLOCKED",
    "YOLO_SOCIAL_IRREVERSIBLE_BLOCKED",
    "YOLO_DESTRUCTIVE_IRREVERSIBLE_BLOCKED",
    "SOCIAL_IRREVERSIBLE_GATE_ESCALATED",
    "DESTRUCTIVE_IRREVERSIBLE_GATE_ESCALATED",
    "REPO_PREFIX_AUTO_APPROVE",
    "OUTBOUND_ALLOW",
    "OUTBOUND_DENY",
    "OUTBOUND_UNCERTAIN",
    "SHELL_ESCALATION_ALLOW",
    "SHELL_ESCALATION_DENY",
    "SHELL_ESCALATION_UNCERTAIN",
    "AUTO_MODE_SUSPENDED",
    "AUTO_MODE_SUSPENDED_ALLOW_ESCALATED",
    # Approval resume: a human answer, checked against the digest the human approved
    "DIGEST_MISMATCH_REJECT",
    "SCRIPT_INTEGRITY_REJECT",
    "SCRIPT_OPERAND_DRIFT_REJECT",
    "DIRECTORY_GRANTED",
    "USER_EDIT_REJECTED",
    # Middleware guards
    "GUARDRAIL_BLOCKED",
    "CLARIFICATION_GUARD_BLOCKED",
]

# A name carrying one of these refused the action it was about, unless it is listed in _ESCALATIONS.
_STOP_MARKERS = ("BLOCK", "DENY", "DENIED", "REJECT")

# Named like a stop, but the action goes on to an approval prompt: the auto-approval route was closed
# and nothing was refused.
_ESCALATIONS: frozenset[DecisionKind] = frozenset(
    {
        "PROTECTED_INSTRUCTION_ALLOWLIST_BLOCKED",
        "FINANCIAL_GATE_ALLOWLIST_BLOCKED",
        "IRREVERSIBLE_ACTION_ALLOWLIST_BLOCKED",
        "YOLO_FINANCIAL_GATE_BLOCKED",
        "YOLO_SOCIAL_IRREVERSIBLE_BLOCKED",
        "YOLO_DESTRUCTIVE_IRREVERSIBLE_BLOCKED",
    }
)

# Telemetry counts every name that carries a block, deny, redact or leak finding, escalations and
# content protections included.
_POLICY_DENIAL_MARKERS = ("BLOCK", "DENY", "REDACT", "LEAK")


def is_blocking_decision(decision: str) -> bool:
    """True when the decision stopped the action it was about, whoever decided."""
    return decision not in _ESCALATIONS and any(marker in decision for marker in _STOP_MARKERS)


def is_policy_denial(decision: str) -> bool:
    """True when the decision name counts as a policy denial in telemetry (``policy_denial_total``, deny totals)."""
    return any(marker in decision for marker in _POLICY_DENIAL_MARKERS)


@dataclass(frozen=True, slots=True)
class SecurityDecision:
    """A single security decision record."""

    tool_name: str
    decision: DecisionKind
    reason: str
    tainted: bool = False
    timestamp: float = field(default_factory=time.time)
    tool_call_id: str | None = None
    device_id: str | None = None
    recovery_hint: str | None = None

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "tool": self.tool_name,
            "decision": self.decision,
            "reason": self.reason,
            "tainted": self.tainted,
            "ts": round(self.timestamp, 3),
        }
        if self.tool_call_id:
            result["tool_call_id"] = self.tool_call_id
        if self.device_id:
            result["device_id"] = self.device_id
        if self.recovery_hint:
            result["recovery_hint"] = self.recovery_hint
        return result


_audit_log_var: ContextVar[list[SecurityDecision]] = ContextVar("security_audit_log")


def record_decision(
    tool_name: str,
    decision: DecisionKind,
    reason: str,
    *,
    tainted: bool = False,
    tool_call_id: str | None = None,
    device_id: str | None = None,
    recovery_hint: str | None = None,
) -> None:
    """Append a security decision to the current session's audit log.

    ``tool_call_id`` links the decision to the concrete tool invocation it
    fired on (when available) so downstream lineage views can attach security
    tags to the exact call.
    """
    try:
        log = _audit_log_var.get()
    except LookupError:
        log = []
        _audit_log_var.set(log)
    log.append(
        SecurityDecision(
            tool_name=tool_name,
            decision=decision,
            reason=reason,
            tainted=tainted,
            tool_call_id=tool_call_id,
            device_id=device_id,
            recovery_hint=recovery_hint,
        )
    )

    if is_policy_denial(decision):
        _count_policy_denial(decision)


def _count_policy_denial(decision: str) -> None:
    try:
        from myrm_agent_harness.observability.metrics.security_metrics import (
            policy_denial_total,
        )
    except ImportError:
        return

    # The label is the first finding found, in this order: redact, deny, leak; otherwise block.
    action = "block"
    if "REDACT" in decision:
        action = "redact"
    elif "DENY" in decision:
        action = "deny"
    elif "LEAK" in decision:
        action = "leak"
    if policy_denial_total:
        policy_denial_total.labels(policy=decision, action=action).inc()


def get_audit_entries() -> list[SecurityDecision]:
    """Retrieve all audit entries for the current session."""
    try:
        return list(_audit_log_var.get())
    except LookupError:
        return []


def reset_audit_log() -> None:
    """Clear the audit log. Call at the start of each Agent run."""
    _audit_log_var.set([])
