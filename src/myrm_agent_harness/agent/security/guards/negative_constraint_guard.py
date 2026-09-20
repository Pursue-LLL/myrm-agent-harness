"""Negative constraint compliance gate for pre-tool execution enforcement.

Intercepts tool invocations before execution when arguments violate active
negative constraints (VETO rules, hard redlines). Prevents recurring errors
and drives in-step agent self-healing via structured diagnostic feedback.

[INPUT]
- agent.security.audit::record_decision (POS: Cross-cutting security decision audit)
- agent.errors.tool_error_category::ToolErrorCategory (POS: Canonical error classification)

[OUTPUT]
- VetoAction: ALLOW / BLOCK / CIRCUIT_BREAK
- NegativeConstraint: Serializable contract definition for veto rules
- NegativeConstraintVerdict: Structured decision with remediation advice
- NegativeConstraintComplianceGate: Session-scoped compliance enforcement gate
- get_compliance_gate / reset_compliance_gate: ContextVar accessors

[POS]
Layer 5 Security Guard, integrated into tool_interceptor_middleware pre-call
phase alongside LoopGuard and FrequencyGuard.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from enum import StrEnum, auto, unique
import json
import re
from typing import Final

_MAX_IN_STEP_RETRIES: Final[int] = 2
_MAX_SCAN_PAYLOAD_BYTES: Final[int] = 64 * 1024  # 64 KB limit to prevent ReDoS on massive inputs


@unique
class VetoAction(StrEnum):
    """Action taken by the negative constraint compliance gate."""

    ALLOW = auto()
    BLOCK = auto()
    CIRCUIT_BREAK = auto()


@dataclass(frozen=True, slots=True)
class NegativeConstraint:
    """Explicit negative constraint specification (VETO rule)."""

    rule_id: str
    name: str
    pattern: str
    tool_scope: str = "*"  # "*" means all tools, or comma-separated / exact tool name
    reason: str = ""
    remediation_advice: str = ""
    priority: int = 0
    is_regex: bool = False


@dataclass(frozen=True, slots=True)
class NegativeConstraintVerdict:
    """Verdict returned by the compliance gate."""

    action: VetoAction
    violated_rule: NegativeConstraint | None = None
    reason: str = ""
    remediation_advice: str = ""
    retry_count: int = 0


class NegativeConstraintComplianceGate:
    """Evaluates tool call arguments against active negative constraints.
    
    Tracks per-rule in-step retries to prevent unbounded recovery loops.
    """

    def __init__(self) -> None:
        self._retry_counters: dict[str, int] = {}
        self._compiled_regex_cache: dict[str, re.Pattern[str]] = {}

    def reset_counters(self) -> None:
        """Clear turn-level retry counters."""
        self._retry_counters.clear()

    def check(
        self,
        tool_name: str,
        tool_args: dict[str, object],
        active_constraints: list[NegativeConstraint] | None,
    ) -> NegativeConstraintVerdict:
        """Evaluate a tool invocation against active constraints.

        Args:
            tool_name: Canonical name of the tool to be executed.
            tool_args: Parameter dictionary prepared for tool execution.
            active_constraints: Constraints currently active in session context.

        Returns:
            NegativeConstraintVerdict with ALLOW, BLOCK, or CIRCUIT_BREAK.
        """
        if not active_constraints:
            return NegativeConstraintVerdict(action=VetoAction.ALLOW)

        serialized_args = self._serialize_args_for_scan(tool_args)

        for constraint in active_constraints:
            if not self._is_tool_in_scope(tool_name, constraint.tool_scope):
                continue

            if self._matches_violation(serialized_args, constraint):
                rule_id = constraint.rule_id
                current_retries = self._retry_counters.get(rule_id, 0) + 1
                self._retry_counters[rule_id] = current_retries

                if current_retries > _MAX_IN_STEP_RETRIES:
                    return NegativeConstraintVerdict(
                        action=VetoAction.CIRCUIT_BREAK,
                        violated_rule=constraint,
                        reason=(
                            f"Negative constraint [{constraint.name}] breached repeatedly "
                            f"({current_retries} attempts). Execution paused for review."
                        ),
                        remediation_advice=constraint.remediation_advice,
                        retry_count=current_retries,
                    )

                return NegativeConstraintVerdict(
                    action=VetoAction.BLOCK,
                    violated_rule=constraint,
                    reason=(
                        f"Action blocked by negative constraint [{constraint.name}]: "
                        f"{constraint.reason or 'forbidden pattern detected'}"
                    ),
                    remediation_advice=constraint.remediation_advice,
                    retry_count=current_retries,
                )

        return NegativeConstraintVerdict(action=VetoAction.ALLOW)

    def _is_tool_in_scope(self, tool_name: str, tool_scope: str) -> bool:
        if not tool_scope or tool_scope == "*":
            return True
        scopes = [s.strip() for s in tool_scope.split(",") if s.strip()]
        return tool_name in scopes or "*" in scopes

    def _serialize_args_for_scan(self, tool_args: dict[str, object]) -> str:
        try:
            raw = json.dumps(tool_args, ensure_ascii=False)
        except Exception:
            raw = str(tool_args)
        return raw[:_MAX_SCAN_PAYLOAD_BYTES]

    def _matches_violation(self, payload: str, constraint: NegativeConstraint) -> bool:
        pattern_str = constraint.pattern.strip()
        if not pattern_str:
            return False

        if constraint.is_regex:
            cached_regex = self._compiled_regex_cache.get(pattern_str)
            if cached_regex is None:
                try:
                    cached_regex = re.compile(pattern_str, re.IGNORECASE)
                    self._compiled_regex_cache[pattern_str] = cached_regex
                except re.error:
                    # Invalid regex fallback to substring search
                    return pattern_str.lower() in payload.lower()
            return cached_regex.search(payload) is not None

        return pattern_str.lower() in payload.lower()


_compliance_gate_var: ContextVar[NegativeConstraintComplianceGate | None] = ContextVar(
    "negative_constraint_compliance_gate",
    default=None,
)


def get_compliance_gate() -> NegativeConstraintComplianceGate:
    """Retrieve or create the context-bound compliance gate instance."""
    gate = _compliance_gate_var.get()
    if gate is None:
        gate = NegativeConstraintComplianceGate()
        _compliance_gate_var.set(gate)
    return gate


def reset_compliance_gate() -> None:
    """Reset the context-bound compliance gate."""
    _compliance_gate_var.set(None)
