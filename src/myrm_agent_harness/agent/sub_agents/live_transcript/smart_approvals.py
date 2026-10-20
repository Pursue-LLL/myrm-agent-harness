# -*- coding: utf-8 -*-
"""Smart Approvals Gate.

Provides isolated single-command review, risk scoring, custom deny rules,
and interactive /deny feedback remediation to keep subagents safe and aligned.

[INPUT]
- hashlib
- re
- time
- threading
- typing
- types

[OUTPUT]
- HIGH_RISK_PATTERNS
- SmartApprovalGate

[POS]
Smart Approvals Gate.
"""

import hashlib
import re
import time
from threading import Lock
from typing import Dict, List, Optional, Set, Tuple

from .types import (
    ApprovalDecision,
    SmartApprovalRequest,
    SmartApprovalResolution,
)

HIGH_RISK_PATTERNS: List[Tuple[str, str, float]] = [
    (r"\brm\s+-(?:r[fF]|f[rR]|rf)\b", "Destructive recursive file removal", 0.95),
    (r"\bmkfs\b", "Filesystem formatting", 0.99),
    (r"\bdd\s+if=", "Raw disk write", 0.95),
    (r"\bgit\s+push\b.*(?:--force|-f\b)", "Force-pushing git history", 0.85),
    (r"\b(?:DROP|TRUNCATE)\s+TABLE\b", "Database destructive operation", 0.90),
    (r"\bchmod\s+777\b", "Global permission elevation", 0.80),
    (r"(?:curl|wget)\b.*\|\s*(?:bash|sh)\b", "Remote script direct execution", 0.90),
    (r"\bkill\s+-9\b", "Unconditional process termination", 0.70),
]


class SmartApprovalGate:
    """Manages command risk evaluation, single-use approvals, and deny feedbacks."""

    def __init__(self, custom_deny_rules: Optional[List[str]] = None) -> None:
        self._lock = Lock()
        self._custom_deny_rules: List[str] = list(custom_deny_rules or [])
        self._pending_requests: Dict[str, SmartApprovalRequest] = {}
        self._consumed_tokens: Set[str] = set()
        self._resolutions: Dict[str, SmartApprovalResolution] = {}

    def add_deny_rule(self, rule_pattern: str) -> None:
        """Add a custom mandatory deny regex rule."""
        with self._lock:
            if rule_pattern not in self._custom_deny_rules:
                self._custom_deny_rules.append(rule_pattern)

    def evaluate_command(
        self,
        task_id: str,
        subagent_id: str,
        command: str,
    ) -> SmartApprovalRequest:
        """Evaluate command risks and create an isolated single-use approval request."""
        cmd_strip = command.strip()
        cmd_hash = hashlib.sha256(f"{task_id}:{cmd_strip}".encode("utf-8")).hexdigest()[:16]
        approval_id = f"appr-{cmd_hash}"

        risk_reasons: List[str] = []
        max_score = 0.0

        # Check custom deny rules first (highest priority)
        with self._lock:
            deny_rules = list(self._custom_deny_rules)

        for rule in deny_rules:
            if re.search(rule, cmd_strip, re.IGNORECASE):
                risk_reasons.append(f"Matched mandatory user deny rule: {rule}")
                max_score = 1.0

        # Check built-in high-risk patterns
        for pattern, reason, score in HIGH_RISK_PATTERNS:
            if re.search(pattern, cmd_strip, re.IGNORECASE):
                risk_reasons.append(reason)
                if score > max_score:
                    max_score = score

        request = SmartApprovalRequest(
            approval_id=approval_id,
            task_id=task_id,
            subagent_id=subagent_id,
            command=cmd_strip,
            command_hash=cmd_hash,
            risk_score=max_score,
            risk_reasons=risk_reasons,
            created_at=time.time(),
        )

        with self._lock:
            self._pending_requests[approval_id] = request

        return request

    def resolve_approval(
        self,
        approval_id: str,
        decision: ApprovalDecision,
        deny_reason: Optional[str] = None,
    ) -> Optional[SmartApprovalResolution]:
        """Resolve an approval request as APPROVED or DENIED with optional feedback."""
        with self._lock:
            req = self._pending_requests.pop(approval_id, None)
            if not req:
                return None

            remediation_prompt: Optional[str] = None
            if decision == ApprovalDecision.DENIED:
                reason_text = deny_reason or "Operation considered too risky by policy."
                remediation_prompt = (
                    f"User/Gate rejected execution of command: `{req.command}`. "
                    f"Denial reason: '{reason_text}'. "
                    f"Remediation guidance: Immediately reconsider your approach, do NOT attempt "
                    f"`{req.command}` again, and propose an alternative safe solution."
                )

            resolution = SmartApprovalResolution(
                approval_id=approval_id,
                decision=decision,
                deny_reason=deny_reason,
                remediation_prompt=remediation_prompt,
                resolved_at=time.time(),
            )
            self._resolutions[approval_id] = resolution
            return resolution

    def consume_approval(self, approval_id: str) -> bool:
        """Consume an approved token once. Subsequent consumptions are rejected."""
        with self._lock:
            if approval_id in self._consumed_tokens:
                return False
            resolution = self._resolutions.get(approval_id)
            if not resolution or resolution.decision != ApprovalDecision.APPROVED:
                return False
            self._consumed_tokens.add(approval_id)
            return True

    def get_resolution(self, approval_id: str) -> Optional[SmartApprovalResolution]:
        """Fetch resolved approval record."""
        with self._lock:
            return self._resolutions.get(approval_id)
