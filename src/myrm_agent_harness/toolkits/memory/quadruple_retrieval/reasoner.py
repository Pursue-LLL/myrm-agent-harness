"""Semantic reasoner module evaluating candidates and executing post-recall reranking.

[INPUT]
- toolkits.memory.quadruple_retrieval.models::ParsedTaskGoal, ReasonerDecisionKind, RerankedMemoryHit, UnifiedCandidateHit (POS: Domain models)

[OUTPUT]
- ReasonerReranker: Semantic inference reranker prioritizing intent-aligned memories.
- ReasonerHarmonizer: Alias for ReasonerReranker.

[POS]
Semantic reasoner module evaluating candidates and executing post-recall reranking.
"""

from __future__ import annotations

import re
from typing import ClassVar

from myrm_agent_harness.toolkits.memory.quadruple_retrieval.models import (
    ParsedTaskGoal,
    ReasonerDecisionKind,
    RerankedMemoryHit,
    UnifiedCandidateHit,
)


class ReasonerReranker:
    """Semantic reasoner evaluating intent alignment, channel consensus, and staleness penalty."""

    _STALE_MARKERS: ClassVar[set[str]] = {
        "deprecated", "superseded", "obsolete", "旧版", "已废弃", "历史遗留", "已弃用",
    }

    def __init__(
        self,
        rrf_k: int = 60,
        min_relevance_threshold: float = 0.15,
        mmr_lambda: float = 0.70,
    ) -> None:
        self._rrf_k = rrf_k
        self._min_relevance_threshold = min_relevance_threshold
        self._mmr_lambda = mmr_lambda

    def rerank_candidates(
        self,
        goal: ParsedTaskGoal,
        candidates: list[UnifiedCandidateHit],
        top_k: int = 5,
    ) -> list[RerankedMemoryHit]:
        """Evaluate fused candidates and produce an auditable ordered hitlist with MMR diversity."""
        if not candidates:
            return []

        scored_evaluations: list[tuple[float, ReasonerDecisionKind, str, UnifiedCandidateHit]] = []

        for candidate in candidates:
            score, decision, rationale = self._evaluate_candidate(goal, candidate)
            scored_evaluations.append((score, decision, rationale, candidate))

        # Sort descending by preliminary harmonized score
        scored_evaluations.sort(key=lambda x: x[0], reverse=True)

        # Apply MMR diversity selection
        selected = self._apply_mmr(scored_evaluations, top_k)

        results: list[RerankedMemoryHit] = []
        for rank_idx, (score, decision, rationale, cand) in enumerate(selected, start=1):
            results.append(
                RerankedMemoryHit(
                    memory_id=cand.memory_id,
                    content=cand.content,
                    final_rank=rank_idx,
                    final_score=round(score, 4),
                    channels_hit=list(cand.channels_hit),
                    reasoner_decision=decision,
                    rationale=rationale,
                    metadata=dict(cand.metadata),
                )
            )

        return results

    def _evaluate_candidate(
        self,
        goal: ParsedTaskGoal,
        candidate: UnifiedCandidateHit,
    ) -> tuple[float, ReasonerDecisionKind, str]:
        """Compute semantic score, determine decision kind, and compose rationale."""
        base_score = candidate.fused_score
        content_lower = candidate.content.lower()
        meta_status = candidate.metadata.get("status", "").lower()
        meta_scope = candidate.metadata.get("scope", "").lower()

        # 1. Check for staleness/deprecation
        is_stale = (
            meta_status in {"deprecated", "obsolete", "archived"}
            or meta_scope == "deprecated"
            or any(marker in content_lower for marker in self._STALE_MARKERS)
        )

        if is_stale:
            stale_score = base_score * 0.35
            rationale = (
                f"Reasoner applied staleness penalty (-65%) due to deprecated/superseded marker: "
                f"status={meta_status or 'unspecified'}."
            )
            return stale_score, ReasonerDecisionKind.PENALIZE_STALE, rationale

        # 2. Check for entity alignment boost
        matched_entities = [
            ent for ent in goal.target_entities
            if ent.lower() in content_lower
        ]
        multi_channel = len(candidate.channels_hit) >= 2

        if matched_entities and multi_channel:
            boosted_score = base_score * 1.35
            rationale = (
                f"Reasoner boosted (+35%) candidate matching explicit entities "
                f"({', '.join(matched_entities)}) and confirmed by multiple channels "
                f"({', '.join(c.value for c in candidate.channels_hit)})."
            )
            return boosted_score, ReasonerDecisionKind.BOOST, rationale

        if base_score < self._min_relevance_threshold:
            rationale = (
                f"Candidate score ({base_score:.3f}) falls below confidence cutoff, marked for suppression."
            )
            return base_score, ReasonerDecisionKind.SUPPRESS, rationale

        rationale = (
            f"Candidate preserved via consensus across channels "
            f"({', '.join(c.value for c in candidate.channels_hit)}) with standard relevance."
        )
        return base_score, ReasonerDecisionKind.KEEP, rationale

    def _apply_mmr(
        self,
        evaluations: list[tuple[float, ReasonerDecisionKind, str, UnifiedCandidateHit]],
        top_k: int,
    ) -> list[tuple[float, ReasonerDecisionKind, str, UnifiedCandidateHit]]:
        """Greedily select candidates maximizing marginal relevance and minimizing overlap."""
        if len(evaluations) <= 1:
            return evaluations[:top_k]

        selected: list[tuple[float, ReasonerDecisionKind, str, UnifiedCandidateHit]] = [evaluations[0]]
        remaining = list(evaluations[1:])

        while len(selected) < top_k and remaining:
            best_idx = -1
            best_mmr_score = float("-inf")

            for idx, (score, _, _, cand) in enumerate(remaining):
                max_sim = max(
                    self._jaccard_similarity(cand.content, sel[3].content)
                    for sel in selected
                )
                mmr_val = self._mmr_lambda * score - (1.0 - self._mmr_lambda) * max_sim
                if mmr_val > best_mmr_score:
                    best_mmr_score = mmr_val
                    best_idx = idx

            if best_idx < 0:
                break
            selected.append(remaining.pop(best_idx))

        return selected

    @staticmethod
    def _jaccard_similarity(text_a: str, text_b: str) -> float:
        """Calculate word-level Jaccard similarity for redundancy penalty."""
        tokens_a = set(re.findall(r"\w+", text_a.lower()))
        tokens_b = set(re.findall(r"\w+", text_b.lower()))
        if not tokens_a or not tokens_b:
            return 0.0
        intersection = len(tokens_a & tokens_b)
        union = len(tokens_a | tokens_b)
        return intersection / union if union > 0 else 0.0

    def harmonize_and_rerank(
        self,
        goal: ParsedTaskGoal,
        candidates: list[UnifiedCandidateHit],
        top_k: int = 5,
        **_kwargs: object,
    ) -> list[RerankedMemoryHit]:
        """Convenience alias for rerank_candidates."""
        return self.rerank_candidates(goal=goal, candidates=candidates, top_k=top_k)


ReasonerHarmonizer = ReasonerReranker
