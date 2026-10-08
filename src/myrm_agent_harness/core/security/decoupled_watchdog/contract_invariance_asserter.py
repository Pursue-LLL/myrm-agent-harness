"""Action contract semantic invariance asserter.

Detects amount drift, recipient drift, parameter fabrication, and destructive
action mismatches between user original intent and tool invocation arguments.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import re

from .types import (
    ActionContractSpec,
    InvarianceAssertionRule,
    ThreatSeverity,
    WatchdogViolationDetail,
)

_FINANCIAL_TOOL_PATTERN = re.compile(r"(?i)(pay|transfer|checkout|buy|tip|charge|billing|purchase)")
_COMMUNICATION_TOOL_PATTERN = re.compile(r"(?i)(send_email|send_message|post_tweet|dispatch|notify)")
_DESTRUCTIVE_TOOL_PATTERN = re.compile(r"(?i)(delete|remove|drop|truncate|purge|wipe|format|destroy)")
_READONLY_INTENT_PATTERN = re.compile(r"(?i)(check|view|get|read|inspect|list|analyze|audit|查看|查询|分析|统计|显示)")
_INTENT_AMOUNT_PATTERN = re.compile(r"(?:[$¥€]|USD|RMB|dollars?|yuan)?\s*(\d+(?:\.\d+)?)\s*(?:dollars?|yuan|元|块)?")


class ActionContractInvarianceAsserter:
    """Evaluates semantic invariance between intent and parameters."""

    def assert_invariance(
        self,
        spec: ActionContractSpec,
        rule: InvarianceAssertionRule | None = None,
    ) -> list[WatchdogViolationDetail]:
        """Perform deterministic invariant checks and return identified violations."""
        violations: list[WatchdogViolationDetail] = []

        # 1. Financial amount drift check
        if _FINANCIAL_TOOL_PATTERN.search(spec.tool_name):
            violations.extend(self._check_financial_drift(spec, rule))

        # 2. Recipient / Destination drift check
        if _COMMUNICATION_TOOL_PATTERN.search(spec.tool_name):
            violations.extend(self._check_recipient_drift(spec, rule))

        # 3. Destructive operation intent alignment check
        if _DESTRUCTIVE_TOOL_PATTERN.search(spec.tool_name):
            violations.extend(self._check_destructive_alignment(spec))

        return violations

    def _check_financial_drift(
        self,
        spec: ActionContractSpec,
        rule: InvarianceAssertionRule | None,
    ) -> list[WatchdogViolationDetail]:
        violations: list[WatchdogViolationDetail] = []
        observed_amount: float | None = None

        for k in ("amount", "price", "cost", "value", "total"):
            if k in spec.arguments:
                val: str | int | float | bool | list[str] = spec.arguments[k]
                if isinstance(val, (int, float)):
                    observed_amount = float(val)
                    break
                if isinstance(val, str):
                    try:
                        observed_amount = float(val.strip().replace("$", "").replace("¥", ""))
                        break
                    except ValueError:
                        pass

        if observed_amount is None:
            return violations

        # Rule bound assertion
        if rule and rule.max_amount_limit > 0.0 and observed_amount > rule.max_amount_limit:
            violations.append(
                WatchdogViolationDetail(
                    violation_type="financial_limit_exceeded",
                    threat_severity=ThreatSeverity.CRITICAL,
                    description=f"Action amount {observed_amount} exceeds explicit rule cap {rule.max_amount_limit}.",
                    parameter_key="amount",
                    observed_value=str(observed_amount),
                    expected_constraint=f"<= {rule.max_amount_limit}",
                )
            )

        # Intent semantic drift assertion
        intent_amounts = [float(m) for m in _INTENT_AMOUNT_PATTERN.findall(spec.user_original_intent) if m]
        if intent_amounts:
            max_intent_amount = max(intent_amounts)
            if observed_amount > max_intent_amount * 1.5:  # Tolerance threshold
                violations.append(
                    WatchdogViolationDetail(
                        violation_type="financial_amount_drift",
                        threat_severity=ThreatSeverity.CRITICAL,
                        description=(
                            f"Action amount {observed_amount} significantly drifts from user intent max "
                            f"{max_intent_amount}."
                        ),
                        parameter_key="amount",
                        observed_value=str(observed_amount),
                        expected_constraint=f"~= {max_intent_amount}",
                    )
                )

        return violations

    def _check_recipient_drift(
        self,
        spec: ActionContractSpec,
        rule: InvarianceAssertionRule | None,
    ) -> list[WatchdogViolationDetail]:
        violations: list[WatchdogViolationDetail] = []
        dest: str = ""

        for k in ("to", "recipient", "target", "email", "destination"):
            if k in spec.arguments and isinstance(spec.arguments[k], str):
                dest = str(spec.arguments[k]).strip()
                break

        if not dest:
            return violations

        if rule and rule.allowed_recipients and dest not in rule.allowed_recipients:
            violations.append(
                WatchdogViolationDetail(
                    violation_type="unauthorized_recipient",
                    threat_severity=ThreatSeverity.HIGH,
                    description=f"Recipient '{dest}' not found in allowed list.",
                    parameter_key="recipient",
                    observed_value=dest,
                    expected_constraint=f"in {list(rule.allowed_recipients)}",
                )
            )

        if rule and rule.prohibited_destinations and dest in rule.prohibited_destinations:
            violations.append(
                WatchdogViolationDetail(
                    violation_type="prohibited_destination_blacklisted",
                    threat_severity=ThreatSeverity.CRITICAL,
                    description=f"Recipient '{dest}' is explicitly blacklisted.",
                    parameter_key="recipient",
                    observed_value=dest,
                    expected_constraint=f"not in {list(rule.prohibited_destinations)}",
                )
            )

        return violations

    def _check_destructive_alignment(
        self,
        spec: ActionContractSpec,
    ) -> list[WatchdogViolationDetail]:
        violations: list[WatchdogViolationDetail] = []

        # If user explicitly requested only read/view, but action is destructive
        if _READONLY_INTENT_PATTERN.search(spec.user_original_intent) and not _DESTRUCTIVE_TOOL_PATTERN.search(
            spec.user_original_intent
        ):
            violations.append(
                WatchdogViolationDetail(
                    violation_type="unauthorized_destructive_action",
                    threat_severity=ThreatSeverity.CRITICAL,
                    description=(
                        f"User intent is read-only ('{spec.user_original_intent[:60]}'), "
                        f"but proposed action '{spec.tool_name}' performs destructive modification."
                    ),
                    parameter_key="tool_name",
                    observed_value=spec.tool_name,
                    expected_constraint="read_only_tool",
                )
            )

        return violations
