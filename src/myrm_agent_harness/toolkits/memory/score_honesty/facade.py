"""Facade suite for retrieval score honesty and raw vs ranking calibration.

Provides an intuitive, high-level API for evaluating candidates, computing
score breakdowns, applying dual-threshold gates, and diagnosing divergence.
"""

from __future__ import annotations

from collections.abc import Sequence

from myrm_agent_harness.toolkits.memory.score_honesty.models import (
    DualThresholdConfig,
    HonestScoredCandidate,
    ScoreHonestyStats,
)
from myrm_agent_harness.toolkits.memory.score_honesty.pipeline import ScoreHonestyPipeline


class RetrievalScoreHonestySuite:
    """Unified coordinator suite for honest memory search scoring."""

    def __init__(self, pipeline: ScoreHonestyPipeline | None = None) -> None:
        self._pipeline = pipeline or ScoreHonestyPipeline()

    def create_candidate(
        self,
        candidate_id: str,
        content: str,
        raw_similarity: float,
        recency_factor: float = 1.0,
        importance_boost: float = 1.0,
        mmr_penalty: float = 0.0,
        rrf_score: float = 0.0,
        metadata: dict[str, str | int | float | bool | None] | None = None,
    ) -> HonestScoredCandidate:
        """Create an honest scored candidate with automatically computed breakdown."""
        breakdown = self._pipeline.compute_breakdown(
            raw_similarity=raw_similarity,
            recency_factor=recency_factor,
            importance_boost=importance_boost,
            mmr_penalty=mmr_penalty,
            rrf_score=rrf_score,
        )
        return HonestScoredCandidate(
            id=candidate_id,
            content=content,
            raw_similarity=breakdown.raw_similarity,
            ranking_score=breakdown.final_ranking_score,
            breakdown=breakdown,
            metadata=metadata or {},
        )

    def evaluate(
        self,
        candidates: Sequence[HonestScoredCandidate],
        config: DualThresholdConfig | None = None,
    ) -> tuple[list[HonestScoredCandidate], ScoreHonestyStats]:
        """Evaluate a batch of candidates against configured dual thresholds."""
        cfg = config or DualThresholdConfig()
        return self._pipeline.process_candidates(candidates, cfg)

    def filter_admitted(
        self,
        candidates: Sequence[HonestScoredCandidate],
        config: DualThresholdConfig | None = None,
    ) -> list[HonestScoredCandidate]:
        """Evaluate and return only candidates admitted by dual threshold gates."""
        evaluated, _ = self.evaluate(candidates, config)
        return [c for c in evaluated if c.verdict and c.verdict.admitted]

    def diagnose_divergence(
        self,
        candidates: Sequence[HonestScoredCandidate],
        config: DualThresholdConfig | None = None,
    ) -> list[HonestScoredCandidate]:
        """Filter candidates where raw similarity and composite ranking decisions disagree."""
        evaluated, _ = self.evaluate(candidates, config)
        return [
            c
            for c in evaluated
            if c.verdict and (c.verdict.passed_raw != c.verdict.passed_ranking)
        ]

    def explain_candidate(self, candidate: HonestScoredCandidate) -> str:
        """Generate human-readable diagnostic explanation of candidate scores."""
        breakdown = candidate.breakdown
        verdict = candidate.verdict
        status = (
            f"Admitted={verdict.admitted} (Stage={verdict.rejection_stage})"
            if verdict
            else "Not Evaluated"
        )
        return (
            f"Candidate [{candidate.id}]: raw_similarity={candidate.raw_similarity:.3f}, "
            f"ranking_score={candidate.ranking_score:.3f} | {status} | "
            f"Breakdown: {breakdown.explanation}"
        )
