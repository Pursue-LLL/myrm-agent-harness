# [POS] src/myrm_agent_harness/toolkits/memory/intent_reflection/probe.py
# [INPUT] collections.abc.Sequence, typing, .types, .classifier, myrm_agent_harness.toolkits.memory.types.ProceduralMemory
# [OUTPUT] PlaybookActivationProbe

from collections.abc import Sequence

from myrm_agent_harness.toolkits.memory.intent_reflection.classifier import (
    IntentLevelClassifier,
)
from myrm_agent_harness.toolkits.memory.intent_reflection.types import (
    IntentTier,
    PlaybookActivationDecision,
)
from myrm_agent_harness.toolkits.memory.types import ProceduralMemory


class PlaybookActivationProbe:
    """Activation probe that selectively awakens relevant playbooks based on intent tier."""

    def __init__(self, classifier: IntentLevelClassifier | None = None) -> None:
        self._classifier = classifier or IntentLevelClassifier()

    def evaluate(
        self,
        query: str,
        candidates: Sequence[ProceduralMemory],
        context: dict[str, str] | None = None,
    ) -> PlaybookActivationDecision:
        """Evaluate query and filter candidate procedural rules accordingly."""
        intent = self._classifier.classify(query=query, context=context)

        # Tier 0 Fast Path: bypass all retrieval and suppress 100% of candidate rules
        if intent.tier == IntentTier.TIER_0_FAST_PATH:
            return PlaybookActivationDecision(
                tier=intent.tier,
                bypass_retrieval=True,
                active_facets=(),
                activated_rules=(),
                suppressed_rules_count=len(candidates),
                decision_reason=(
                    "Tier 0 fast path bypassed retrieval and suppressed all candidate rules."
                ),
            )

        active_rules: list[ProceduralMemory] = []
        suppressed_count = 0
        target_facets = set(intent.suggested_facets)

        for rule in candidates:
            # Drop retired or inactive rules
            if not getattr(rule, "is_active", True):
                suppressed_count += 1
                continue
            if getattr(rule, "lifecycle_state", "active") == "retired":
                suppressed_count += 1
                continue

            # Deep reasoning tier activates all active candidate playbooks
            if intent.tier == IntentTier.TIER_3_DEEP_REASONING:
                active_rules.append(rule)
                continue

            # Domain facet filtering for Tier 1 and Tier 2
            rule_facets = getattr(rule, "facets", None)
            if not rule_facets:
                rule_facets = ["global"]

            rule_facet_set = set(rule_facets)
            if "global" in rule_facet_set or bool(rule_facet_set & target_facets):
                active_rules.append(rule)
            else:
                suppressed_count += 1

        return PlaybookActivationDecision(
            tier=intent.tier,
            bypass_retrieval=False,
            active_facets=intent.suggested_facets,
            activated_rules=tuple(active_rules),
            suppressed_rules_count=suppressed_count,
            decision_reason=(
                f"Activated {len(active_rules)} playbooks matching facets {intent.suggested_facets} "
                f"(suppressed {suppressed_count})."
            ),
        )
