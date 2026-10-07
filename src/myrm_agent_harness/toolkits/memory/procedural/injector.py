"""Procedural rule injector for prompt safety boundaries and tool call preflight enforcement.

[INPUT]
- toolkits.memory.procedural.models::ProceduralRule, RuleInjectionContext, RuleScope (POS: Data models for
  User Intervention to Procedural Memory Distillation Engine.)

[OUTPUT]
- ProceduralRuleInjector: Matches scoped procedural rules and injects non-negotiable safety guards.

[POS]
Procedural rule injector for prompt safety boundaries and tool call preflight enforcement.
"""

import re
from collections.abc import Sequence

from .models import (
    ProceduralRule,
    RuleInjectionContext,
    RuleScope,
)


class ProceduralRuleInjector:
    """Matches scoped procedural rules and injects non-negotiable safety guards."""

    def __init__(self) -> None:
        """Initialize procedural rule injector."""

    def match_rules(
        self,
        rules: Sequence[ProceduralRule],
        target_tool: str | None = None,
        target_path: str | None = None,
        workspace: str | None = None,
    ) -> list[ProceduralRule]:
        """Filter rules that are active and match the invocation scope and trigger context."""
        matched: list[ProceduralRule] = []

        for rule in rules:
            if not rule.is_active:
                continue

            # Scope boundary validation
            if not self._is_scope_applicable(rule, workspace):
                continue

            # Trigger pattern validation
            if self._matches_trigger(rule, target_tool, target_path):
                matched.append(rule)

        return matched

    def assemble_prompt_guard(
        self,
        matched_rules: Sequence[ProceduralRule],
    ) -> RuleInjectionContext:
        """Synthesize matched procedural rules into an authoritative system prompt constraint segment."""
        if not matched_rules:
            return RuleInjectionContext(
                injected_rules=[],
                prompt_segment="",
                enforced_preflights=[],
                blocked_actions=[],
            )

        blocked: list[str] = []
        preflights: list[str] = []

        for r in matched_rules:
            if r.prohibited_action and r.prohibited_action not in blocked:
                blocked.append(r.prohibited_action)
            if r.required_preflight and r.required_preflight not in preflights:
                preflights.append(r.required_preflight)

        lines: list[str] = [
            "[PROCEDURAL SAFETY GUARD - USER ENFORCED ENVIRONMENT CONSTRAINTS]",
            "CRITICAL: The user has previously intervened with non-negotiable operational rules.",
            "You MUST strictly adhere to the following procedural constraints before and during execution:",
        ]

        if blocked:
            lines.append("STRICTLY PROHIBITED ACTIONS:")
            for b in blocked:
                lines.append(f"  - {b}")

        if preflights:
            lines.append("MANDATORY PREFLIGHT REQUIREMENTS:")
            for p in preflights:
                lines.append(f"  - {p}")

        lines.append(
            "Do NOT bypass, disregard, or re-attempt previously corrected erroneous operations."
        )

        segment = "\n".join(lines)

        return RuleInjectionContext(
            injected_rules=list(matched_rules),
            prompt_segment=segment,
            enforced_preflights=preflights,
            blocked_actions=blocked,
        )

    def validate_action(
        self,
        rule: ProceduralRule,
        tool_name: str,
        arguments: dict[str, str],
    ) -> tuple[bool, str]:
        """Inspect a planned tool call against the procedural rule to prevent recurrence of errors.

        Returns:
            Tuple of (is_allowed, rejection_reason).
        """
        if not rule.is_active:
            return True, ""

        arg_corpus = " ".join(f"{k}={v}" for k, v in arguments.items()).lower()
        trigger = rule.trigger_pattern.lower().strip()

        # Disallow empty or wildcard triggers from substring-blocking everything
        if not trigger or trigger in (".*", "*"):
            return True, ""

        # Check if the tool invocation targets a strictly prohibited asset
        is_triggered = trigger in arg_corpus or (re.search(re.escape(trigger), arg_corpus) is not None)
        if is_triggered and rule.prohibited_action:
            return (
                False,
                f"BLOCKED by procedural rule '{rule.title}': {rule.prohibited_action}",
            )

        return True, ""

    def _is_scope_applicable(self, rule: ProceduralRule, workspace: str | None) -> bool:
        """Verify whether rule applies to the given workspace environment."""
        if rule.scope == RuleScope.GLOBAL:
            return True

        if rule.scope == RuleScope.WORKSPACE:
            if not rule.scope_target:
                return True
            return bool(
                workspace
                and (
                    workspace.startswith(rule.scope_target)
                    or rule.scope_target.startswith(workspace)
                )
            )

        return True

    def _matches_trigger(
        self,
        rule: ProceduralRule,
        target_tool: str | None,
        target_path: str | None,
    ) -> bool:
        """Check if target tool or file path triggers the rule."""
        if rule.scope == RuleScope.GLOBAL:
            return True

        pattern = rule.trigger_pattern.strip()
        if pattern in (".*", "*", ""):
            return True

        if target_tool and pattern.lower() in target_tool.lower():
            return True

        return bool(target_path and pattern.lower() in target_path.lower())
