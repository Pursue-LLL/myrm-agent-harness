"""Action Impact Filtering Gate executing 3-tier admission routing."""

from collections.abc import Sequence

from .evaluator import FutureActionImpactEvaluator
from .models import (
    ActionImpactAssessment,
    ActionImpactTier,
    BatchFilteringSummary,
)


class ActionImpactFilteringGate:
    """Pre-admission gate intercepting extracted memory candidates before persistence."""

    def __init__(
        self,
        evaluator: FutureActionImpactEvaluator | None = None,
    ) -> None:
        """Initialize filtering gate with action impact evaluator."""
        self._evaluator = evaluator or FutureActionImpactEvaluator()
        self._total_evaluated = 0
        self._total_prevented_pollution = 0

    @property
    def total_facts_evaluated(self) -> int:
        """Return cumulative count of facts assessed across all calls."""
        return self._total_evaluated

    @property
    def cumulative_noise_reduction_ratio(self) -> float:
        """Return global ratio of transient/chitchat noise prevented from entering long-term store."""
        if self._total_evaluated == 0:
            return 1.0
        return self._total_prevented_pollution / self._total_evaluated

    def assess_fact(self, fact_text: str) -> ActionImpactAssessment:
        """Evaluate a single candidate fact against future action impact criteria."""
        return self._evaluator.evaluate_fact(fact_text)

    def filter_and_route(
        self,
        candidate_facts: Sequence[str],
    ) -> tuple[list[ActionImpactAssessment], list[ActionImpactAssessment], list[ActionImpactAssessment]]:
        """Filter facts and partition them into three distinct storage tiers.

        Tiers:
            1. Persist (score >= 0.80): Permanent facts and policies.
            2. Buffer (0.40 <= score < 0.80): Ephemeral L2 session state.
            3. Discard (score < 0.40): Chitchat and low-value speculations.

        Args:
            candidate_facts: Sequence of raw fact texts extracted from user dialogue.

        Returns:
            Tuple of (persisted_assessments, buffered_assessments, discarded_assessments).
        """
        persisted: list[ActionImpactAssessment] = []
        buffered: list[ActionImpactAssessment] = []
        discarded: list[ActionImpactAssessment] = []

        for f in candidate_facts:
            assessment = self.assess_fact(f)
            self._total_evaluated += 1

            if assessment.assigned_tier == ActionImpactTier.TIER_LONG_TERM_PERSIST:
                persisted.append(assessment)
            elif assessment.assigned_tier == ActionImpactTier.TIER_SESSION_BUFFER:
                buffered.append(assessment)
                self._total_prevented_pollution += 1
            else:
                discarded.append(assessment)
                self._total_prevented_pollution += 1

        return persisted, buffered, discarded

    def evaluate_batch(
        self,
        candidate_facts: Sequence[str],
    ) -> tuple[list[ActionImpactAssessment], BatchFilteringSummary]:
        """Perform batch admission filtering and return approved facts with metric summary.

        Args:
            candidate_facts: Input candidate facts.

        Returns:
            Tuple of (approved_long_term_facts, summary_statistics).
        """
        persisted, buffered, discarded = self.filter_and_route(candidate_facts)
        total = len(candidate_facts)
        non_persisted = len(buffered) + len(discarded)
        ratio = (non_persisted / total) if total > 0 else 1.0

        summary = BatchFilteringSummary(
            total_candidates=total,
            persisted_count=len(persisted),
            session_buffered_count=len(buffered),
            discarded_count=len(discarded),
            noise_reduction_ratio=round(ratio, 4),
        )
        return persisted, summary
