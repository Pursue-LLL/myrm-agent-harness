"""Core score honesty and dual-threshold processing pipeline.

Evaluates raw vector similarity and multi-stage composite ranking scores
independently, preventing threshold corruption and computing attribution breakdowns.
"""

from __future__ import annotations

from collections.abc import Sequence

from myrm_agent_harness.toolkits.memory.score_honesty.models import (
    DualThresholdConfig,
    HonestScoredCandidate,
    RejectionStage,
    ScoreBreakdown,
    ScoreHonestyStats,
    ThresholdEvaluationVerdict,
)


class ScoreHonestyPipeline:
    """Pipeline for computing score breakdowns and applying dual-threshold gates."""

    @staticmethod
    def compute_breakdown(
        raw_similarity: float,
        recency_factor: float = 1.0,
        importance_boost: float = 1.0,
        mmr_penalty: float = 0.0,
        rrf_score: float = 0.0,
    ) -> ScoreBreakdown:
        """Derive composite ranking score with full white-box factor breakdown."""
        clamped_raw = min(1.0, max(0.0, float(raw_similarity)))
        clamped_recency = min(2.0, max(0.0, float(recency_factor)))
        clamped_importance = min(2.0, max(0.0, float(importance_boost)))
        clamped_mmr = min(1.0, max(0.0, float(mmr_penalty)))
        clamped_rrf = max(0.0, float(rrf_score))

        # Base product of semantic relevance, recency multiplier, and importance
        multiplicative_base = clamped_raw * clamped_recency * clamped_importance

        # Integrate RRF if present (RRF standard scores are typically 1 / (60 + rank))
        # Scaled smoothly to blend with direct similarity
        rrf_additive = min(0.5, clamped_rrf * 10.0) if clamped_rrf > 0.0 else 0.0

        raw_composite = (multiplicative_base * 0.85) + rrf_additive - (clamped_mmr * 0.25)
        final_ranking = min(1.0, max(0.0, round(raw_composite, 4)))

        explanation = (
            f"raw={clamped_raw:.3f} * recency={clamped_recency:.2f} * "
            f"importance={clamped_importance:.2f} + rrf={clamped_rrf:.3f} - "
            f"mmr={clamped_mmr:.2f} => ranking={final_ranking:.3f}"
        )

        return ScoreBreakdown(
            raw_similarity=clamped_raw,
            recency_factor=clamped_recency,
            importance_boost=clamped_importance,
            mmr_penalty=clamped_mmr,
            rrf_score=clamped_rrf,
            final_ranking_score=final_ranking,
            explanation=explanation,
        )

    @staticmethod
    def evaluate_verdict(
        raw_similarity: float,
        ranking_score: float,
        config: DualThresholdConfig,
    ) -> ThresholdEvaluationVerdict:
        """Evaluate candidate against dual threshold policy."""
        passed_raw = raw_similarity >= config.raw_similarity_threshold
        passed_ranking = ranking_score >= config.ranking_score_threshold

        if passed_raw and passed_ranking:
            return ThresholdEvaluationVerdict(
                passed_raw=True,
                passed_ranking=True,
                admitted=True,
                rejection_stage=RejectionStage.NONE,
                rejection_reason=None,
            )

        if not passed_raw and not passed_ranking:
            return ThresholdEvaluationVerdict(
                passed_raw=False,
                passed_ranking=False,
                admitted=False,
                rejection_stage=RejectionStage.BOTH_BELOW_THRESHOLD,
                rejection_reason=(
                    f"Rejected by both gates: raw {raw_similarity:.3f} < "
                    f"{config.raw_similarity_threshold:.3f} and ranking "
                    f"{ranking_score:.3f} < {config.ranking_score_threshold:.3f}"
                ),
            )

        if not passed_raw:
            # Passed ranking, failed raw
            admitted = not config.strict_mode
            reason = (
                f"Candidate raw similarity {raw_similarity:.3f} below floor "
                f"{config.raw_similarity_threshold:.3f}"
            )
            return ThresholdEvaluationVerdict(
                passed_raw=False,
                passed_ranking=True,
                admitted=admitted,
                rejection_stage=RejectionStage.RAW_BELOW_THRESHOLD,
                rejection_reason=None if admitted else reason,
            )

        # Passed raw, failed ranking
        admitted = not config.strict_mode
        reason = (
            f"Candidate ranking score {ranking_score:.3f} below floor "
            f"{config.ranking_score_threshold:.3f}"
        )
        return ThresholdEvaluationVerdict(
            passed_raw=True,
            passed_ranking=False,
            admitted=admitted,
            rejection_stage=RejectionStage.RANKING_BELOW_THRESHOLD,
            rejection_reason=None if admitted else reason,
        )

    def process_candidates(
        self,
        candidates: Sequence[HonestScoredCandidate],
        config: DualThresholdConfig,
    ) -> tuple[list[HonestScoredCandidate], ScoreHonestyStats]:
        """Apply dual thresholds, attach verdicts, sort by ranking, and aggregate metrics."""
        evaluated: list[HonestScoredCandidate] = []
        raw_admitted = 0
        ranking_admitted = 0
        both_passed = 0
        divergences = 0
        total_raw = 0.0
        total_ranking = 0.0

        for cand in candidates:
            verdict = self.evaluate_verdict(
                raw_similarity=cand.raw_similarity,
                ranking_score=cand.ranking_score,
                config=config,
            )
            updated = cand.model_copy(update={"verdict": verdict})
            evaluated.append(updated)

            total_raw += cand.raw_similarity
            total_ranking += cand.ranking_score

            if verdict.passed_raw:
                raw_admitted += 1
            if verdict.passed_ranking:
                ranking_admitted += 1
            if verdict.passed_raw and verdict.passed_ranking:
                both_passed += 1
            if verdict.passed_raw != verdict.passed_ranking:
                divergences += 1

        # Sort all evaluated candidates stably by ranking_score descending, then raw_similarity descending
        evaluated.sort(
            key=lambda c: (c.ranking_score, c.raw_similarity),
            reverse=True,
        )

        n = len(candidates)
        admitted_list = [c for c in evaluated if c.verdict and c.verdict.admitted]
        admitted_count = len(admitted_list)
        rejected_count = n - admitted_count
        div_rate = (divergences / n) if n > 0 else 0.0
        mean_raw = round(total_raw / n, 4) if n > 0 else 0.0
        mean_ranking = round(total_ranking / n, 4) if n > 0 else 0.0

        stats = ScoreHonestyStats(
            total_candidates=n,
            admitted_count=admitted_count,
            rejected_count=rejected_count,
            raw_admitted_count=raw_admitted,
            ranking_admitted_count=ranking_admitted,
            both_passed_count=both_passed,
            divergence_count=divergences,
            divergence_rate=round(div_rate, 4),
            mean_raw_similarity=mean_raw,
            mean_ranking_score=mean_ranking,
        )

        return evaluated, stats
