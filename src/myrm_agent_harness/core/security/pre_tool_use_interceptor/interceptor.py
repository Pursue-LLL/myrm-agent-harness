"""Deterministic PreToolUse Hook Interceptor enforcing hard non-negotiable gates.

[INPUT]
- Tool names, execution payload strings (command lines, scripts, queries), and custom rules.

[OUTPUT]
- PreToolUseInterceptResult verdict and potential HardGateSecurityRejection exception.

[POS]
- First line of defense physically intercepting high-risk tool execution before dispatch.
"""

from __future__ import annotations

import re

from myrm_agent_harness.core.security.pre_tool_use_interceptor.rules import (
    DEFAULT_HARD_RULES,
)
from myrm_agent_harness.core.security.pre_tool_use_interceptor.types import (
    HardGateActionVerdict,
    HardGateSecurityRejectionError,
    HardRuleSpec,
    PreToolUseInterceptResult,
)


class PreToolUseHookInterceptor:
    """Pre-tool dispatch hook evaluating non-negotiable hard security invariants."""

    def __init__(self, initial_rules: list[HardRuleSpec] | None = None) -> None:
        """Initialize interceptor with rules catalog."""
        self._rules: dict[str, HardRuleSpec] = {}
        rules_to_load = initial_rules if initial_rules is not None else DEFAULT_HARD_RULES
        for r in rules_to_load:
            self._rules[r.rule_id] = r

    def add_rule(self, rule: HardRuleSpec) -> None:
        """Register or update a hard invariant rule."""
        self._rules[rule.rule_id] = rule

    def get_rules(self) -> list[HardRuleSpec]:
        """Return all registered hard rules."""
        return list(self._rules.values())

    def set_rule_enabled(self, rule_id: str, enabled: bool) -> bool:
        """Enable or disable a specific rule."""
        if rule_id not in self._rules:
            return False
        old_rule = self._rules[rule_id]
        self._rules[rule_id] = HardRuleSpec(
            rule_id=old_rule.rule_id,
            category=old_rule.category,
            pattern=old_rule.pattern,
            description=old_rule.description,
            enabled=enabled,
        )
        return True

    def intercept(
        self,
        tool_name: str,
        payload_str: str,
        raise_on_block: bool = False,
    ) -> PreToolUseInterceptResult:
        """Evaluate attempted tool call against hard rules before dispatch.

        Args:
            tool_name: Name of tool being invoked (e.g., 'run_command', 'write_to_file').
            payload_str: String representation of command line or file content.
            raise_on_block: If True, raises HardGateSecurityRejection immediately upon denial.

        Returns:
            PreToolUseInterceptResult verdict.

        Raises:
            HardGateSecurityRejection: If raise_on_block is True and a hard rule is breached.
        """
        for rule in self._rules.values():
            if not rule.enabled:
                continue

            if re.search(rule.pattern, payload_str, re.IGNORECASE):
                reason = (
                    f"Execution blocked by deterministic hard invariant rule "
                    f"'{rule.rule_id}' ({rule.category.value}): {rule.description}"
                )
                if raise_on_block:
                    raise HardGateSecurityRejectionError(
                        rule_id=rule.rule_id,
                        category=rule.category,
                        reason=reason,
                    )

                return PreToolUseInterceptResult(
                    verdict=HardGateActionVerdict.BLOCK,
                    blocked_rule_id=rule.rule_id,
                    rule_category=rule.category,
                    rejection_reason=reason,
                    detected_pattern=rule.pattern,
                )

        return PreToolUseInterceptResult(verdict=HardGateActionVerdict.ALLOW)
