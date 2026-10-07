"""Memory rule reinforcement emphasis gate.

Manages high-priority rule tagging, attention decay tracking and suppression,
and dynamic top-of-prompt directive synthesis across multi-turn sessions.

[INPUT]
- runtime.context.memory_reinforce_skill_attach_types::ReinforcedMemoryRule, ReinforcementPriorityKind (POS:
  Types and data models for memory rule reinforcement emphasis gate and mid-session skill attachment.)

[OUTPUT]
- MemoryReinforceEmphasisGate: Gatekeeper regulating reinforced memory rules and prompt attention weighting.

[POS]
Memory rule reinforcement emphasis gate.
"""

from __future__ import annotations

import time

from myrm_agent_harness.runtime.context.memory_reinforce_skill_attach_types import (
    ReinforcedMemoryRule,
    ReinforcementPriorityKind,
)


class MemoryReinforceEmphasisGate:
    """Gatekeeper regulating reinforced memory rules and prompt attention weighting."""

    def __init__(self, default_boost_turns: int = 5) -> None:
        self._default_boost_turns = max(default_boost_turns, 1)
        self._rules: dict[str, dict[str, ReinforcedMemoryRule]] = {}

    def register_rule(
        self,
        session_id: str,
        rule_id: str,
        content: str,
        category: str = "general",
        priority: ReinforcementPriorityKind = ReinforcementPriorityKind.NORMAL,
        metadata: dict[str, str] | None = None,
    ) -> ReinforcedMemoryRule:
        """Register or initialize a memory directive in the specified session."""
        session_rules = self._rules.setdefault(session_id, {})
        decay_rounds = self._default_boost_turns if priority != ReinforcementPriorityKind.NORMAL else 0

        rule = ReinforcedMemoryRule(
            rule_id=rule_id,
            rule_content=content.strip(),
            category=category.strip(),
            priority=priority,
            reinforce_count=1 if priority != ReinforcementPriorityKind.NORMAL else 0,
            last_reinforced_at=time.time(),
            decay_suppression_rounds=decay_rounds,
            metadata=dict(metadata or {}),
        )
        session_rules[rule_id] = rule
        return rule

    def emphasize_rule(
        self,
        session_id: str,
        rule_id: str,
        boost_turns: int | None = None,
    ) -> ReinforcedMemoryRule:
        """Elevate an existing rule to high attention priority with decay suppression."""
        session_rules = self._rules.setdefault(session_id, {})
        existing = session_rules.get(rule_id)
        now = time.time()
        turns = boost_turns if boost_turns is not None else self._default_boost_turns

        if existing is None:
            # Auto-register as emphasized rule
            rule = ReinforcedMemoryRule(
                rule_id=rule_id,
                rule_content=rule_id,
                category="general",
                priority=ReinforcementPriorityKind.HIGH_ATTENTION_PRIORITY,
                reinforce_count=1,
                last_reinforced_at=now,
                decay_suppression_rounds=turns,
                metadata={},
            )
            session_rules[rule_id] = rule
            return rule

        new_priority = (
            ReinforcementPriorityKind.PINNED_SYSTEM_DIRECTIVE
            if existing.priority == ReinforcementPriorityKind.PINNED_SYSTEM_DIRECTIVE
            else ReinforcementPriorityKind.HIGH_ATTENTION_PRIORITY
        )

        updated = ReinforcedMemoryRule(
            rule_id=existing.rule_id,
            rule_content=existing.rule_content,
            category=existing.category,
            priority=new_priority,
            reinforce_count=existing.reinforce_count + 1,
            last_reinforced_at=now,
            decay_suppression_rounds=max(existing.decay_suppression_rounds, turns),
            metadata=dict(existing.metadata),
        )
        session_rules[rule_id] = updated
        return updated

    def pin_directive(self, session_id: str, rule_id: str) -> ReinforcedMemoryRule:
        """Permanently pin a critical rule to prevent any attention decay."""
        session_rules = self._rules.setdefault(session_id, {})
        existing = session_rules.get(rule_id)
        now = time.time()

        if existing is None:
            rule = ReinforcedMemoryRule(
                rule_id=rule_id,
                rule_content=rule_id,
                category="general",
                priority=ReinforcementPriorityKind.PINNED_SYSTEM_DIRECTIVE,
                reinforce_count=1,
                last_reinforced_at=now,
                decay_suppression_rounds=99999,
                metadata={},
            )
            session_rules[rule_id] = rule
            return rule

        updated = ReinforcedMemoryRule(
            rule_id=existing.rule_id,
            rule_content=existing.rule_content,
            category=existing.category,
            priority=ReinforcementPriorityKind.PINNED_SYSTEM_DIRECTIVE,
            reinforce_count=existing.reinforce_count + 1,
            last_reinforced_at=now,
            decay_suppression_rounds=99999,
            metadata=dict(existing.metadata),
        )
        session_rules[rule_id] = updated
        return updated

    def step_turn_decay(self, session_id: str) -> tuple[str, ...]:
        """Advance one turn and decrement decay protection counters.

        Returns the tuple of rule IDs whose boost expired and reverted to normal.
        """
        session_rules = self._rules.get(session_id, {})
        expired_rules: list[str] = []

        for r_id, rule in list(session_rules.items()):
            # Pinned directives never decay
            if rule.priority == ReinforcementPriorityKind.PINNED_SYSTEM_DIRECTIVE:
                continue

            if rule.priority == ReinforcementPriorityKind.HIGH_ATTENTION_PRIORITY:
                rem = rule.decay_suppression_rounds - 1
                if rem <= 0:
                    # Decay back to normal priority
                    session_rules[r_id] = ReinforcedMemoryRule(
                        rule_id=rule.rule_id,
                        rule_content=rule.rule_content,
                        category=rule.category,
                        priority=ReinforcementPriorityKind.NORMAL,
                        reinforce_count=rule.reinforce_count,
                        last_reinforced_at=rule.last_reinforced_at,
                        decay_suppression_rounds=0,
                        metadata=dict(rule.metadata),
                    )
                    expired_rules.append(r_id)
                else:
                    session_rules[r_id] = ReinforcedMemoryRule(
                        rule_id=rule.rule_id,
                        rule_content=rule.rule_content,
                        category=rule.category,
                        priority=rule.priority,
                        reinforce_count=rule.reinforce_count,
                        last_reinforced_at=rule.last_reinforced_at,
                        decay_suppression_rounds=rem,
                        metadata=dict(rule.metadata),
                    )

        return tuple(expired_rules)

    def get_active_emphasis_rules(
        self, session_id: str
    ) -> tuple[ReinforcedMemoryRule, ...]:
        """Return all active emphasized or pinned rules sorted by priority and recency."""
        session_rules = self._rules.get(session_id, {})
        active = [
            r
            for r in session_rules.values()
            if r.priority != ReinforcementPriorityKind.NORMAL
        ]

        def _sort_key(item: ReinforcedMemoryRule) -> tuple[int, int, float]:
            priority_rank = (
                2
                if item.priority == ReinforcementPriorityKind.PINNED_SYSTEM_DIRECTIVE
                else 1
            )
            return (priority_rank, item.reinforce_count, item.last_reinforced_at)

        active.sort(key=_sort_key, reverse=True)
        return tuple(active)

    def render_emphasis_prompt_block(self, session_id: str) -> str:
        """Render markdown prompt block injecting reinforced directives into attention space."""
        rules = self.get_active_emphasis_rules(session_id)
        if not rules:
            return ""

        lines: list[str] = [
            "### [HIGH ATTENTION ACTIVE DIRECTIVES - STRONGLY ENFORCED]",
            "The following directives have been actively reinforced by the user/governor. You MUST strictly adhere to them:",
        ]

        for rule in rules:
            badge = "PINNED" if rule.priority == ReinforcementPriorityKind.PINNED_SYSTEM_DIRECTIVE else f"EMPHASIZED x{rule.reinforce_count}"
            lines.append(f"- **[{rule.category}]** ({badge}): {rule.rule_content}")

        lines.append("")
        return "\n".join(lines)
