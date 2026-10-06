# [POS] toolkits/memory/strategies/hindsight/reflection_buffer.py
# [INPUT] HindsightRule, PreExecutionWarning, ReflectionBufferConfig
# [OUTPUT] HindsightReflectionBuffer

"""Retrospective reflection buffer storing rules and injecting proactive pre-execution warnings."""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.strategies.hindsight.types import (
    HindsightRule,
    PreExecutionWarning,
    ReflectionBufferConfig,
)


class HindsightReflectionBuffer:
    """In-memory managed buffer of actionable counterfactual failure rules."""

    def __init__(self, config: ReflectionBufferConfig | None = None) -> None:
        self.config = config or ReflectionBufferConfig()
        self._rules: dict[str, HindsightRule] = {}

    def get_all_rules(self) -> list[HindsightRule]:
        """Return all persisted rules ordered by hit count descending."""
        return sorted(self._rules.values(), key=lambda r: r.hit_count, reverse=True)

    def record_rule(self, rule: HindsightRule) -> HindsightRule:
        """Register or reinforce a hindsight rule in the reflection buffer."""
        # 1. Deduplication and reinforcement: match existing rule with identical pattern
        for existing_id, existing in self._rules.items():
            if (
                existing.task_pattern == rule.task_pattern
                and existing.mistake_signature == rule.mistake_signature
            ):
                updated = HindsightRule(
                    rule_id=existing_id,
                    task_pattern=existing.task_pattern,
                    mistake_signature=existing.mistake_signature,
                    correction_advice=existing.correction_advice,
                    tags=list(set(existing.tags + rule.tags)),
                    confidence=min(1.0, existing.confidence + 0.1),
                    hit_count=existing.hit_count + 1,
                    created_at=existing.created_at,
                )
                self._rules[existing_id] = updated
                return updated

        # 2. Check capacity limits and evict least used if needed
        if len(self._rules) >= self.config.max_capacity:
            evict_candidate = min(
                self._rules.values(), key=lambda r: (r.hit_count, r.confidence)
            )
            del self._rules[evict_candidate.rule_id]

        # 3. Add fresh rule
        self._rules[rule.rule_id] = rule
        return rule

    def match_warnings(
        self,
        task_goal: str,
        intended_tools: list[str] | None = None,
        top_k: int = 3,
    ) -> list[PreExecutionWarning]:
        """Identify relevant failure pitfalls and generate proactive warnings for a new task."""
        if not self._rules or not task_goal:
            return []

        goal_lower = task_goal.lower()
        tools_set = {t.lower() for t in intended_tools} if intended_tools else set()

        scored_rules: list[tuple[float, HindsightRule]] = []

        for rule in self._rules.values():
            if rule.confidence < self.config.min_confidence:
                continue

            match_score = 0.0

            # Tag alignment score
            for tag in rule.tags:
                tag_lower = tag.lower()
                if tag_lower in goal_lower:
                    match_score += 1.0
                if tag_lower in tools_set:
                    match_score += 2.0  # Stronger weight for explicit tool intention

            # Substring / pattern overlap score
            pattern_clean = rule.task_pattern.lower()
            if pattern_clean in goal_lower or goal_lower in pattern_clean:
                match_score += 3.0

            # Scale by rule confidence and historical hit count
            total_relevance = match_score * rule.confidence * (1.0 + 0.1 * min(rule.hit_count, 5))

            if total_relevance > 0.0:
                scored_rules.append((total_relevance, rule))

        scored_rules.sort(key=lambda item: item[0], reverse=True)

        warnings: list[PreExecutionWarning] = []
        for _, rule in scored_rules[:top_k]:
            warnings.append(
                PreExecutionWarning(
                    rule_id=rule.rule_id,
                    task_pattern=rule.task_pattern,
                    warning_text=f"Historical Pitfall: {rule.mistake_signature}",
                    recommended_action=f"Recommended Pre-Action: {rule.correction_advice}",
                    confidence=rule.confidence,
                )
            )

        return warnings

    def get_stats(self) -> dict[str, int | float]:
        """Return operational telemetry of the reflection buffer."""
        total = len(self._rules)
        if total == 0:
            return {"total_rules": 0, "avg_confidence": 0.0, "total_hits": 0}

        avg_conf = sum(r.confidence for r in self._rules.values()) / total
        total_hits = sum(r.hit_count for r in self._rules.values())
        return {
            "total_rules": total,
            "avg_confidence": round(avg_conf, 4),
            "total_hits": total_hits,
        }
