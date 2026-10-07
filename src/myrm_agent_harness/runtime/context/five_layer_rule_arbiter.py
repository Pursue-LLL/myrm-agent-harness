"""Five-layer rule hierarchy topology arbiter and anti-bloat garbage collector.

Enforces deterministic precedence:
    Corrections (100) > VOICE (80) > CONTEXT (60) > AGENTS (40) > SOUL (20)
Resolves semantic conflicts and prunes ephemeral clutter from long-term memory.

[INPUT]
- runtime.context.multi_gateway_trust_types::FiveLayerRuleMatrix, RuleConflictResolution, RuleEntry,
  RuleLayerKind (POS: Strongly typed data contracts for Model-Harness orthogonal decoupling and
  multi-gateway trust.)

[OUTPUT]
- FiveLayerRuleArbiter: Arbitrates rule collisions across the 5 layers and performs anti-bloat pruning.

[POS]
Five-layer rule hierarchy topology arbiter and anti-bloat garbage collector.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from myrm_agent_harness.runtime.context.multi_gateway_trust_types import (
    FiveLayerRuleMatrix,
    RuleConflictResolution,
    RuleEntry,
    RuleLayerKind,
)


class FiveLayerRuleArbiter:
    """Arbitrates rule collisions across the 5 layers and performs anti-bloat pruning."""

    EPHEMERAL_PATTERNS: tuple[str, ...] = (
        r"\b(only\s+for\s+this\s+turn|once|temporary|debug\s+now|just\s+this\s+time)\b",
        r"\b(仅限本次|仅此一次|临时测试|单次生效)\b",
    )

    def __init__(self) -> None:
        self._compiled_ephemeral = [
            re.compile(p, re.IGNORECASE) for p in self.EPHEMERAL_PATTERNS
        ]

    def detect_ephemeral(self, content: str) -> bool:
        """Check if rule content exhibits markers of ephemeral, one-off instructions."""
        return any(pattern.search(content) is not None for pattern in self._compiled_ephemeral)

    def resolve_conflicts_and_assemble(
        self,
        matrix: FiveLayerRuleMatrix,
    ) -> tuple[tuple[RuleEntry, ...], tuple[RuleConflictResolution, ...]]:
        """Sort rules by strict topological priority and arbitrate category conflicts.

        Returns (surviving_active_rules, resolutions_list).
        """
        all_rules: list[RuleEntry] = list(matrix.all_rules())
        # Sort in descending order of priority score
        all_rules.sort(key=lambda r: r.layer.priority_score, reverse=True)

        surviving_by_category: dict[str, RuleEntry] = {}
        suppressed_by_category: dict[str, list[RuleEntry]] = {}

        for rule in all_rules:
            cat = rule.category.strip().lower()
            if not cat:
                # If uncategorized, avoid category suppression
                cat = f"_uncategorized_{rule.rule_id}"

            if cat not in surviving_by_category:
                surviving_by_category[cat] = rule
                suppressed_by_category[cat] = []
            else:
                suppressed_by_category[cat].append(rule)

        resolutions: list[RuleConflictResolution] = []
        for cat, winner in surviving_by_category.items():
            losers = suppressed_by_category.get(cat, [])
            if losers:
                rationale = (
                    f"Rule '{winner.rule_id}' in layer [{winner.layer.value.upper()}] (score {winner.layer.priority_score}) "
                    f"superceded {len(losers)} conflicting rule(s) in lower layers for category '{cat}'."
                )
                resolutions.append(
                    RuleConflictResolution(
                        winning_rule=winner,
                        suppressed_rules=tuple(losers),
                        rationale=rationale,
                    )
                )

        # Preserve the sorted order of surviving rules
        surviving_rules = tuple(
            r for r in all_rules if r in surviving_by_category.values()
        )
        return surviving_rules, tuple(resolutions)

    def garbage_collect_rules(
        self,
        rules: Sequence[RuleEntry],
        drop_ephemeral: bool = True,
    ) -> tuple[tuple[RuleEntry, ...], tuple[RuleEntry, ...]]:
        """Run GC to filter out stale ephemeral directives and redundant duplicates.

        Returns (retained_rules, pruned_rules).
        """
        retained: list[RuleEntry] = []
        pruned: list[RuleEntry] = []
        seen_fingerprints: set[str] = set()

        for rule in rules:
            # Detect ephemeral flag or textual markers
            is_one_off = rule.is_ephemeral or self.detect_ephemeral(rule.content)
            if drop_ephemeral and is_one_off:
                pruned.append(rule)
                continue

            # Exact fingerprint deduplication within category
            fingerprint = f"{rule.category.lower()}:{rule.content.strip().lower()}"
            if fingerprint in seen_fingerprints:
                pruned.append(rule)
                continue

            seen_fingerprints.add(fingerprint)
            retained.append(rule)

        return tuple(retained), tuple(pruned)

    def render_markdown_context(
        self,
        active_rules: Sequence[RuleEntry],
    ) -> str:
        """Render active rules into well-structured markdown organized by hierarchy."""
        by_layer: dict[RuleLayerKind, list[RuleEntry]] = {
            layer: [] for layer in RuleLayerKind
        }
        for rule in active_rules:
            by_layer[rule.layer].append(rule)

        lines: list[str] = ["# Active Operational Rules (Topological Precedence)\n"]
        # Render from highest priority (CORRECTIONS) to lowest (SOUL)
        for layer in sorted(RuleLayerKind, key=lambda x: x.priority_score, reverse=True):
            rules = by_layer[layer]
            if not rules:
                continue
            lines.append(f"## Layer: {layer.value.upper()} (Priority {layer.priority_score})")
            for r in rules:
                lines.append(f"- **[{r.category}]** {r.content}")
            lines.append("")

        return "\n".join(lines).strip()
