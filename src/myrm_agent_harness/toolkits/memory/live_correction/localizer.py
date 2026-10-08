"""Target node semantic localizer identifying existing memory candidates for live correction.

[INPUT]
- slot: CorrectionSlot
- candidates: Sequence[TargetNodeCandidate]

[OUTPUT]
- Optional[TargetNodeCandidate]: Best matching target node or None if no candidate exceeds threshold

[POS]
myrm_agent_harness.toolkits.memory.live_correction.localizer
"""

from __future__ import annotations

from collections.abc import Sequence

from myrm_agent_harness.toolkits.memory.live_correction.models import (
    CorrectionSlot,
    TargetNodeCandidate,
)


class CorrectionTargetLocalizer:
    """Locates conflicting or outdated memory nodes matching the correction slot."""

    def __init__(self, match_threshold: float = 0.3) -> None:
        self.match_threshold = match_threshold

    def localize(
        self,
        slot: CorrectionSlot,
        candidates: Sequence[TargetNodeCandidate],
    ) -> TargetNodeCandidate | None:
        """Find the most relevant existing memory node to be corrected or superseded."""
        if not candidates:
            return None

        best_candidate: TargetNodeCandidate | None = None
        best_score = 0.0

        for candidate in candidates:
            score = self._compute_similarity(slot, candidate)
            if score > best_score:
                best_score = score
                best_candidate = candidate

        if best_candidate and best_score >= self.match_threshold:
            # Return updated candidate with calculated match score
            return TargetNodeCandidate(
                memory_id=best_candidate.memory_id,
                content=best_candidate.content,
                cube_id=best_candidate.cube_id,
                match_score=best_score,
                attributes=best_candidate.attributes,
            )

        return None

    def _compute_similarity(
        self,
        slot: CorrectionSlot,
        candidate: TargetNodeCandidate,
    ) -> float:
        content_lower = candidate.content.lower()

        # Strong signal: exact substring match of negated value
        if slot.negated_value and slot.negated_value.lower() in content_lower:
            return 0.95

        # Subject match
        if slot.subject and slot.subject.lower() in content_lower:
            return 0.80

        # Token overlap ratio
        terms = set()
        if slot.negated_value:
            terms.update(slot.negated_value.lower().split())
        if slot.subject:
            terms.update(slot.subject.lower().split())

        if not terms:
            # Fallback to key terms from raw utterance
            terms = {t for t in slot.raw_utterance.lower().split() if len(t) > 1}

        if not terms:
            return 0.0

        overlap = sum(1 for term in terms if term in content_lower)
        ratio = overlap / len(terms)

        return float(ratio)
