"""Confidence Decay Governor and Dual-Blind Conflict Arbitration Engine."""

import math
import re
from collections.abc import Sequence
from datetime import UTC, datetime

from .models import (
    ArbitrationAction,
    ConflictArbitrationReport,
    EvolvingMemoryRule,
    RuleStatus,
)


class ConfidenceDecayGovernor:
    """Manages temporal confidence half-life decay and conflict arbitration."""

    def __init__(
        self,
        decay_cutoff_threshold: float = 0.30,
        reinforcement_alpha: float = 0.15,
        confidence_delta_margin: float = 0.15,
    ) -> None:
        """Initialize governor configuration.

        Args:
            decay_cutoff_threshold: Threshold below which rules become DECAYED.
            reinforcement_alpha: Multiplier for logarithmic reinforcement bonus.
            confidence_delta_margin: Minimal delta margin required for clear replacement.
        """
        self._decay_cutoff_threshold = decay_cutoff_threshold
        self._reinforcement_alpha = reinforcement_alpha
        self._confidence_delta_margin = confidence_delta_margin

    def compute_effective_confidence(
        self,
        rule: EvolvingMemoryRule,
        current_time: datetime | None = None,
    ) -> float:
        """Calculate time-decayed effective confidence with reinforcement amplification.

        Formula:
            delta_days = (now - last_accessed_at).total_seconds() / 86400
            decay = 2 ** (-delta_days / half_life_days)
            boost = 1 + alpha * ln(1 + reinforcement_count)
            effective = min(1.0, max(0.0, base_confidence * decay * boost))
        """
        now = current_time or datetime.now(UTC)
        last_seen = rule.last_accessed_at
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=UTC)
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)

        delta_seconds = max(0.0, (now - last_seen).total_seconds())
        delta_days = delta_seconds / 86400.0

        decay_factor = math.pow(2.0, -delta_days / max(0.1, rule.half_life_days))
        reinforce_boost = 1.0 + self._reinforcement_alpha * math.log(1.0 + rule.reinforcement_count)

        effective = rule.confidence * decay_factor * reinforce_boost
        return max(0.0, min(1.0, effective))

    def evaluate_lifecycle(
        self,
        rule: EvolvingMemoryRule,
        current_time: datetime | None = None,
    ) -> EvolvingMemoryRule:
        """Update rule status based on decayed confidence threshold."""
        effective_conf = self.compute_effective_confidence(rule, current_time)

        if rule.status == RuleStatus.ACTIVE and effective_conf < self._decay_cutoff_threshold:
            rule.status = RuleStatus.DECAYED
        elif rule.status == RuleStatus.DECAYED and effective_conf >= self._decay_cutoff_threshold:
            rule.status = RuleStatus.ACTIVE

        return rule

    def touch(
        self,
        rule: EvolvingMemoryRule,
        access_time: datetime | None = None,
    ) -> EvolvingMemoryRule:
        """Record a successful retrieval touch, refreshing access timestamp."""
        now = access_time or datetime.now(UTC)
        rule.last_accessed_at = now
        rule.access_count += 1
        return self.evaluate_lifecycle(rule, now)

    def reinforce(
        self,
        rule: EvolvingMemoryRule,
        reinforcement_time: datetime | None = None,
    ) -> EvolvingMemoryRule:
        """Reinforce rule with positive cross-session evidence verification."""
        now = reinforcement_time or datetime.now(UTC)
        rule.updated_at = now
        rule.last_accessed_at = now
        rule.reinforcement_count += 1
        # Slightly boost base confidence upon repeated independent confirmation
        rule.confidence = min(1.0, rule.confidence + 0.05)
        return self.evaluate_lifecycle(rule, now)

    def arbitrate_conflict(
        self,
        old_rule: EvolvingMemoryRule,
        new_rule: EvolvingMemoryRule,
        current_time: datetime | None = None,
    ) -> ConflictArbitrationReport:
        """Perform dual-blind arbitration between conflicting rule assertions.

        Determines whether to replace old rule, uphold old rule, quarantine both, or merge.
        """
        now = current_time or datetime.now(UTC)
        is_conflict, conflict_reason = self._detect_semantic_conflict(old_rule, new_rule)

        if not is_conflict:
            return ConflictArbitrationReport(
                conflict_detected=False,
                old_rule_id=old_rule.rule_id,
                new_rule_id=new_rule.rule_id,
                action=ArbitrationAction.MERGE,
                rationale=f"No direct factual conflict identified: {conflict_reason}",
                resolved_rule=new_rule,
            )

        old_eff = self.compute_effective_confidence(old_rule, now)
        new_eff = self.compute_effective_confidence(new_rule, now)

        delta = new_eff - old_eff

        if delta >= self._confidence_delta_margin:
            # New rule decisively supersedes decayed/weaker old rule
            new_rule.status = RuleStatus.ACTIVE
            old_rule.status = RuleStatus.REJECTED
            return ConflictArbitrationReport(
                conflict_detected=True,
                old_rule_id=old_rule.rule_id,
                new_rule_id=new_rule.rule_id,
                action=ArbitrationAction.REPLACE_WITH_NEW,
                rationale=(
                    f"New rule confidence ({new_eff:.2f}) decisively outweights "
                    f"old rule ({old_eff:.2f}) by delta={delta:.2f} >= {self._confidence_delta_margin}."
                ),
                resolved_rule=new_rule,
            )

        if delta <= -self._confidence_delta_margin:
            # Old rule remains strongly corroborated and superior
            old_rule.status = RuleStatus.ACTIVE
            new_rule.status = RuleStatus.REJECTED
            return ConflictArbitrationReport(
                conflict_detected=True,
                old_rule_id=old_rule.rule_id,
                new_rule_id=new_rule.rule_id,
                action=ArbitrationAction.UPHOLD_OLD,
                rationale=(
                    f"Old rule confidence ({old_eff:.2f}) decisively surpasses "
                    f"new candidate ({new_eff:.2f}) by delta={-delta:.2f}."
                ),
                resolved_rule=old_rule,
            )

        # Confidence is closely contested without decisive margin: quarantine both to prevent drift
        old_rule.status = RuleStatus.QUARANTINED
        new_rule.status = RuleStatus.QUARANTINED
        return ConflictArbitrationReport(
            conflict_detected=True,
            old_rule_id=old_rule.rule_id,
            new_rule_id=new_rule.rule_id,
            action=ArbitrationAction.QUARANTINE_BOTH,
            rationale=(
                f"Contested confidence between old ({old_eff:.2f}) and new ({new_eff:.2f}) "
                f"is within ambiguity margin (+-{self._confidence_delta_margin}). Both rules quarantined."
            ),
            resolved_rule=None,
        )

    def filter_active_rules(
        self,
        rules: Sequence[EvolvingMemoryRule],
        current_time: datetime | None = None,
    ) -> list[EvolvingMemoryRule]:
        """Return only currently non-decayed active rules."""
        active: list[EvolvingMemoryRule] = []
        for r in rules:
            updated = self.evaluate_lifecycle(r, current_time)
            if updated.status == RuleStatus.ACTIVE:
                active.append(updated)
        return active

    def _detect_semantic_conflict(
        self,
        rule_a: EvolvingMemoryRule,
        rule_b: EvolvingMemoryRule,
    ) -> tuple[bool, str]:
        """Detect direct syntactic and polarity conflicts in rule statements."""
        # Domain mismatch -> cannot conflict directly
        if rule_a.domain != rule_b.domain:
            return False, "Different functional domains."

        text_a = rule_a.statement.lower().strip()
        text_b = rule_b.statement.lower().strip()

        if text_a == text_b:
            return False, "Identical statements."

        # Detect negation polarity conflict (e.g., 'always use X' vs 'never use X' or 'is X' vs 'is not X')
        has_not_a = bool(re.search(r"\b(not|never|disable|false)\b", text_a))
        has_not_b = bool(re.search(r"\b(not|never|disable|false)\b", text_b))

        # Check overlapping subject nouns
        tokens_a = set(re.findall(r"\b\w{3,}\b", text_a)) - {"not", "never", "always", "the", "and"}
        tokens_b = set(re.findall(r"\b\w{3,}\b", text_b)) - {"not", "never", "always", "the", "and"}
        overlap = tokens_a.intersection(tokens_b)

        if overlap and (has_not_a != has_not_b):
            return True, f"Polarity opposition detected over shared concepts: {overlap}"

        # Key-value assignment opposition (e.g., "branch is main" vs "branch is master")
        kv_pattern = r"(?:branch|port|version|env|database|mode)\s+(?:is|=|set to)\s+([\w\d_-]+)"
        match_a = re.search(kv_pattern, text_a)
        match_b = re.search(kv_pattern, text_b)
        if match_a and match_b and match_a.group(1) != match_b.group(1):
            return True, f"Conflicting slot assignment: '{match_a.group(1)}' vs '{match_b.group(1)}'"

        return False, "No direct contradiction patterns identified."
