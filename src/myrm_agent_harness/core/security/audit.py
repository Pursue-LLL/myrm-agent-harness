"""Audit Trail — structured decision log for tool-call security.

Records every security decision made during an Agent session into a
ContextVar accumulator. The log can be retrieved at the end of a run
(e.g. for Cron metadata) or inspected for debugging.

[INPUT]
- (none — self-contained, pure standard library)

[OUTPUT]
- SecurityDecision: a single audit entry
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
    "CANARY_LEAKED",
]


@dataclass(frozen=True, slots=True)
class SecurityDecision:
    """A single security decision record."""

    tool_name: str
    decision: DecisionKind
    reason: str
    tainted: bool = False
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, object]:
        return {
            "tool": self.tool_name,
            "decision": self.decision,
            "reason": self.reason,
            "tainted": self.tainted,
            "ts": round(self.timestamp, 3),
        }


_audit_log_var: ContextVar[list[SecurityDecision]] = ContextVar("security_audit_log")


def record_decision(tool_name: str, decision: DecisionKind, reason: str, *, tainted: bool = False) -> None:
    """Append a security decision to the current session's audit log."""
    try:
        log = _audit_log_var.get()
    except LookupError:
        log = []
        _audit_log_var.set(log)
    log.append(SecurityDecision(tool_name=tool_name, decision=decision, reason=reason, tainted=tainted))

    if "BLOCK" in decision or "DENY" in decision or "REDACT" in decision or "LEAK" in decision:
        try:
            from myrm_agent_harness.observability.metrics.security_metrics import policy_denial_total
            # Extract basic action like block, redact, deny
            action = "block"
            if "REDACT" in decision:
                action = "redact"
            elif "DENY" in decision:
                action = "deny"
            elif "LEAK" in decision:
                action = "leak"
            if policy_denial_total:
                policy_denial_total.labels(policy=decision, action=action).inc()
        except ImportError:
            pass


def get_audit_entries() -> list[SecurityDecision]:
    """Retrieve all audit entries for the current session."""
    try:
        return list(_audit_log_var.get())
    except LookupError:
        return []


def reset_audit_log() -> None:
    """Clear the audit log. Call at the start of each Agent run."""
    _audit_log_var.set([])
