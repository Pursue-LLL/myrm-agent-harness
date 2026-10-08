"""Hierarchical deterministic rule cascade loader inspired by Claude Code.

[INPUT]
- toolkits.memory.rule_cascade.models::CascadedRuleSet, DeterministicRuleEntry (POS: Types and models for rule
  cascade.)

[OUTPUT]
- DeterministicRuleCascadeLoader: Hierarchical deterministic rule cascade loader inspired by Claude Code.

[POS]
Hierarchical deterministic rule cascade loader inspired by Claude Code.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import PurePosixPath

from myrm_agent_harness.toolkits.memory.rule_cascade.models import (
    CascadedRuleSet,
    DeterministicRuleEntry,
)

logger = logging.getLogger(__name__)


def _normalize_path(path_str: str) -> str:
    """Normalize a posix path string to standard root-leading representation."""
    cleaned = path_str.strip()
    if not cleaned or cleaned == "/":
        return "/"
    normalized = str(PurePosixPath(cleaned))
    if not normalized.startswith("/"):
        normalized = "/" + normalized
    return normalized


def _get_ancestor_paths(target_path: str) -> list[str]:
    """Generate ascending sequence of ancestor paths from root to target."""
    normalized = _normalize_path(target_path)
    if normalized == "/":
        return ["/"]

    parts = [p for p in normalized.split("/") if p]
    paths: list[str] = ["/"]
    current = ""
    for part in parts:
        current += f"/{part}"
        paths.append(current)
    return paths


class DeterministicRuleCascadeLoader:
    """Hierarchical deterministic rule cascade loader inspired by Claude Code.

    Rules are resolved along the directory tree from root to leaf. Deeper path rules
    override ancestors with the same rule identifier or title, ensuring 100% deterministic
    boundary enforcement without probabilistic vector recall.
    """

    def __init__(self) -> None:
        self._rules: dict[str, DeterministicRuleEntry] = {}

    def register_rule(self, rule: DeterministicRuleEntry) -> None:
        """Register a deterministic engineering constraint."""
        self._rules[rule.rule_id] = rule

    def register_rules(self, rules: list[DeterministicRuleEntry]) -> None:
        """Register multiple engineering constraints."""
        for r in rules:
            self.register_rule(r)

    def get_all_rules(self) -> list[DeterministicRuleEntry]:
        """Return all registered deterministic rules."""
        return list(self._rules.values())

    def clear(self) -> None:
        """Clear all registered rules."""
        self._rules.clear()

    def resolve_cascade(self, target_path: str) -> CascadedRuleSet:
        """Resolve all applicable rules along the ancestor path hierarchy for target_path."""
        ancestors = _get_ancestor_paths(target_path)
        path_depth_map: dict[str, int] = {p: idx for idx, p in enumerate(ancestors)}

        # Find all rules whose scope_path matches one of the ancestor directories
        matching_rules: list[DeterministicRuleEntry] = []
        for rule in self._rules.values():
            if not rule.is_enforced:
                continue
            rule_path = _normalize_path(rule.metadata.scope_path)
            if rule_path in path_depth_map:
                matching_rules.append(rule)

        # Collision resolution:
        # 1. Group rules by title (or identifier)
        # 2. Prefer deeper directory path
        # 3. If same directory depth, prefer higher source_authority
        by_title: dict[str, list[DeterministicRuleEntry]] = defaultdict(list)
        for r in matching_rules:
            by_title[r.title.strip().lower()].append(r)

        resolved_rules: list[DeterministicRuleEntry] = []
        for _title_key, candidates in by_title.items():
            if len(candidates) == 1:
                resolved_rules.append(candidates[0])
                continue

            # Sort candidate rules by:
            # - directory depth ascending (deeper is higher depth index)
            # - source_authority ascending
            candidates.sort(
                key=lambda item: (
                    path_depth_map.get(_normalize_path(item.metadata.scope_path), 0),
                    item.metadata.source_authority,
                )
            )
            # The last item is the winner (deepest & highest authority)
            resolved_rules.append(candidates[-1])

        # Sort the final resolved rules by their rule_id for determinism
        resolved_rules.sort(key=lambda item: item.rule_id)

        # Source breakdown statistics
        sources_breakdown: dict[str, int] = defaultdict(int)
        for r in resolved_rules:
            sources_breakdown[r.metadata.source.value] += 1

        return CascadedRuleSet(
            target_path=_normalize_path(target_path),
            inherited_rules=resolved_rules,
            effective_rules_count=len(resolved_rules),
            sources_breakdown=dict(sources_breakdown),
        )
