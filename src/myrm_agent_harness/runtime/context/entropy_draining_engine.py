"""Architecture entropy draining engine and dynamic working set rules pruner.

Orchestrates path-scoped matching, rule conflict resolution, and stale
rule archive pruning to prevent context poisoning and rule bloat.

[INPUT]
- runtime.context.path_scoped_rule_matcher::PathScopedRuleMatcher (POS: Path-scoped and task-phase rule
  matching router for dynamic working set slicing.)
- runtime.context.rule_telemetry_ledger::RuleTelemetryLedger (POS: Telemetry and usage ledger for dynamic
  rules.)
- runtime.context.working_set_rules_types::ActiveWorkingSet, EntropyAuditReport, EntropyConflictItem,
  RuleItem, RuleSeverity (POS: Data types and schemas for dynamic working-set rules and architecture entropy
  draining.)

[OUTPUT]
- EntropyDrainingEngine: Manages dynamic working set rules pruning and architectural entropy drainage.

[POS]
Architecture entropy draining engine and dynamic working set rules pruner.
"""

from __future__ import annotations

from myrm_agent_harness.runtime.context.path_scoped_rule_matcher import (
    PathScopedRuleMatcher,
)
from myrm_agent_harness.runtime.context.rule_telemetry_ledger import (
    RuleTelemetryLedger,
)
from myrm_agent_harness.runtime.context.working_set_rules_types import (
    ActiveWorkingSet,
    EntropyAuditReport,
    EntropyConflictItem,
    RuleItem,
    RuleSeverity,
)


class EntropyDrainingEngine:
    """Manages dynamic working set rules pruning and architectural entropy drainage."""

    def __init__(self, matcher: PathScopedRuleMatcher | None = None) -> None:
        self.matcher = matcher or PathScopedRuleMatcher()
        self.telemetry = RuleTelemetryLedger()
        self._rules: dict[str, RuleItem] = {}
        self._archived_rule_ids: set[str] = set()

    def register_rule(self, rule: RuleItem) -> None:
        """Register a new or updated rule item."""
        self._rules[rule.rule_id] = rule
        self.telemetry.register_rule(rule.rule_id)

    def register_rules(self, rules: list[RuleItem]) -> None:
        """Batch register rule items."""
        for r in rules:
            self.register_rule(r)

    def get_pruned_working_set_rules(
        self,
        working_set: ActiveWorkingSet,
    ) -> list[RuleItem]:
        """Obtain deduplicated, conflict-free, path-scoped rules for current working set."""
        # 1. Filter out already archived rules
        active_candidates = [
            r for r_id, r in self._rules.items() if r_id not in self._archived_rule_ids
        ]

        # 2. Match against active paths and current task phase
        matched = self.matcher.match_rules(active_candidates, working_set)

        # 3. Resolve competing conflict keys (keep higher severity or first)
        resolved = self._resolve_conflicts(matched)

        # 4. Record telemetry hits
        for r in resolved:
            first_path = working_set.active_paths[0] if working_set.active_paths else None
            self.telemetry.record_match(r.rule_id, working_set.current_phase, first_path)

        return resolved

    def drain_entropy(self, min_inactivity_threshold: int = 0) -> EntropyAuditReport:
        """Perform architecture entropy sweep: archive stale rules and detect conflicts."""
        all_active = [
            r for r_id, r in self._rules.items() if r_id not in self._archived_rule_ids
        ]
        conflicts = self._detect_all_conflicts(all_active)

        # Identify stale rules that never triggered
        stale_ids = self.telemetry.get_stale_rule_ids(
            all_active, min_inactivity_threshold=min_inactivity_threshold
        )

        for s_id in stale_ids:
            self._archived_rule_ids.add(s_id)
            self.telemetry.mark_archived(s_id)

        retained_count = len(self._rules) - len(self._archived_rule_ids)
        total_count = len(self._rules)
        efficiency = (
            (len(self._archived_rule_ids) / total_count) if total_count > 0 else 0.0
        )

        return EntropyAuditReport(
            total_rules_inspected=total_count,
            active_rules_retained=retained_count,
            stale_rules_archived=sorted(stale_ids),
            detected_conflicts=conflicts,
            pruning_efficiency_ratio=efficiency,
        )

    def render_rules_prompt_xml(self, rules: list[RuleItem]) -> str:
        """Render active rules into structured XML block for injection into prompt."""
        if not rules:
            return ""

        lines: list[str] = ["<dynamic_working_set_rules>"]
        for r in rules:
            lines.append(f'  <rule id="{r.rule_id}" severity="{r.severity.value}">')
            lines.append(f"    <title>{r.title}</title>")
            lines.append(f"    <content>{r.content}</content>")
            lines.append("  </rule>")
        lines.append("</dynamic_working_set_rules>")
        return "\n".join(lines)

    def _resolve_conflicts(self, rules: list[RuleItem]) -> list[RuleItem]:
        """Eliminate lower-precedence rules that clash on conflict_keys."""
        severity_rank = {
            RuleSeverity.MANDATORY: 3,
            RuleSeverity.RECOMMENDED: 2,
            RuleSeverity.ADVISORY: 1,
        }

        # Key -> highest ranking rule
        key_winners: dict[str, RuleItem] = {}
        conflict_free: list[RuleItem] = []

        for rule in rules:
            if not rule.conflict_keys:
                conflict_free.append(rule)
                continue

            for key in rule.conflict_keys:
                if key not in key_winners:
                    key_winners[key] = rule
                else:
                    curr_winner = key_winners[key]
                    if severity_rank[rule.severity] > severity_rank[curr_winner.severity]:
                        key_winners[key] = rule

        # Combine unique winners with conflict-free rules
        unique_winner_ids: set[str] = {r.rule_id for r in key_winners.values()}
        final_list = [r for r in conflict_free if r.rule_id not in unique_winner_ids]
        final_list.extend(key_winners.values())

        return final_list

    def _detect_all_conflicts(self, rules: list[RuleItem]) -> list[EntropyConflictItem]:
        """Map and report all conflicting rule pairings across the catalog."""
        key_to_rules: dict[str, list[str]] = {}
        for r in rules:
            for k in r.conflict_keys:
                key_to_rules.setdefault(k, []).append(r.rule_id)

        conflicts: list[EntropyConflictItem] = []
        for key, r_ids in key_to_rules.items():
            if len(r_ids) > 1:
                conflicts.append(
                    EntropyConflictItem(
                        conflict_key=key,
                        competing_rule_ids=sorted(r_ids),
                        description=f"Multiple rules compete on constraint key '{key}'.",
                    )
                )

        return conflicts
