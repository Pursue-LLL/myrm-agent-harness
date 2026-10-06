"""Telemetry and usage ledger for dynamic rules.

Tracks rule activations, hit counts, path footprints, and dilution indices
to identify stale rules and guide architecture entropy draining.
"""

from __future__ import annotations

from myrm_agent_harness.runtime.context.working_set_rules_types import (
    RuleItem,
    RuleTelemetryRecord,
    TaskPhase,
)


class RuleTelemetryLedger:
    """In-memory telemetry ledger tracking usage of rules across sessions."""

    def __init__(self) -> None:
        self._records: dict[str, RuleTelemetryRecord] = {}

    def register_rule(self, rule_id: str) -> None:
        """Ensure a rule has a tracking record."""
        if rule_id not in self._records:
            self._records[rule_id] = RuleTelemetryRecord(rule_id=rule_id)

    def record_match(
        self,
        rule_id: str,
        phase: TaskPhase,
        matched_path: str | None = None,
    ) -> None:
        """Record an active match / injection of a rule."""
        self.register_rule(rule_id)
        record = self._records[rule_id]
        record.hits_count += 1
        record.last_matched_phase = phase
        if matched_path:
            record.matched_paths.add(matched_path)

    def mark_archived(self, rule_id: str) -> None:
        """Mark rule as archived from active working sets."""
        if rule_id in self._records:
            self._records[rule_id].is_archived = True

    def get_record(self, rule_id: str) -> RuleTelemetryRecord | None:
        """Fetch telemetry record for a specific rule."""
        return self._records.get(rule_id)

    def get_stale_rule_ids(
        self,
        all_rules: list[RuleItem],
        min_inactivity_threshold: int = 0,
    ) -> list[str]:
        """Identify rules with zero activations that should be considered for draining."""
        stale: list[str] = []
        for rule in all_rules:
            record = self._records.get(rule.rule_id)
            if not record or (record.hits_count <= min_inactivity_threshold and not record.is_archived):
                stale.append(rule.rule_id)
        return stale

    def compute_dilution_ratio(self, total_available_rules: int, matched_rules_count: int) -> float:
        """Calculate the context pollution / dilution ratio of injecting all rules vs matched subset."""
        if total_available_rules == 0:
            return 0.0
        # The higher the ratio of avoided rules, the higher the dilution saved
        avoided = max(0, total_available_rules - matched_rules_count)
        return avoided / total_available_rules
