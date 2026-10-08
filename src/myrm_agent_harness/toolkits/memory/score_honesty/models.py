"""Score honesty and raw vs ranking models.

Provides strongly-typed schemas for separating raw semantic vector similarity
from multi-stage pipeline ranking scores, preventing threshold corruption and
enabling white-box explainability.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class RejectionStage(StrEnum):
    """Stage where a search candidate was filtered out."""

    NONE = "none"
    RAW_BELOW_THRESHOLD = "raw_below_threshold"
    RANKING_BELOW_THRESHOLD = "ranking_below_threshold"
    BOTH_BELOW_THRESHOLD = "both_below_threshold"


class ScoreBreakdown(BaseModel):
    """Fine-grained, white-box attribution for composite score derivation."""

    raw_similarity: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Physical cosine/BM25 similarity before multi-stage reranking",
    )
    recency_factor: float = Field(
        default=1.0,
        ge=0.0,
        le=2.0,
        description="Recency multiplier or decay coefficient applied to candidate",
    )
    importance_boost: float = Field(
        default=1.0,
        ge=0.0,
        le=2.0,
        description="Subjective or frequency-based importance weight boost",
    )
    mmr_penalty: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Diversity penalty applied during Maximal Marginal Relevance",
    )
    rrf_score: float = Field(
        default=0.0,
        ge=0.0,
        description="Reciprocal rank fusion score across multi-query variants",
    )
    final_ranking_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Composite ranking score used for final top-k ordering",
    )
    explanation: str = Field(
        default="",
        description="Human and agent-readable summary of score calculation",
    )

    @field_validator("raw_similarity", "final_ranking_score", mode="before")
    @classmethod
    def _clamp_unit_interval(cls, v: object) -> float:
        try:
            val = float(v)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 0.0
        if val != val:  # NaN guard
            return 0.0
        return min(1.0, max(0.0, val))


class DualThresholdConfig(BaseModel):
    """Independent thresholds for physical semantic relevance vs composite ranking."""

    raw_similarity_threshold: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="Floor applied to physical vector store similarity",
    )
    ranking_score_threshold: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Floor applied to composite ranking score after pipeline",
    )
    strict_mode: bool = Field(
        default=True,
        description="If True, candidate must pass BOTH raw and ranking thresholds",
    )


class ThresholdEvaluationVerdict(BaseModel):
    """Diagnostic outcome of dual-threshold evaluation for a candidate."""

    passed_raw: bool = Field(
        default=False,
        description="Whether candidate raw similarity meets or exceeds raw threshold",
    )
    passed_ranking: bool = Field(
        default=False,
        description="Whether candidate ranking score meets or exceeds ranking threshold",
    )
    admitted: bool = Field(
        default=False,
        description="Final admission decision under configured threshold policy",
    )
    rejection_stage: RejectionStage = Field(
        default=RejectionStage.NONE,
        description="Rejection classification stage",
    )
    rejection_reason: str | None = Field(
        default=None,
        description="Detailed diagnostics if candidate was rejected",
    )


class HonestScoredCandidate(BaseModel):
    """Candidate memory entry with strictly separated raw and ranking scores."""

    id: str = Field(description="Unique identifier of candidate memory item")
    content: str = Field(description="Textual payload of memory item")
    raw_similarity: float = Field(
        ge=0.0,
        le=1.0,
        description="Raw vector semantic similarity score",
    )
    ranking_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Synthesized multi-stage ranking score",
    )
    breakdown: ScoreBreakdown = Field(
        description="Detailed score composition factors",
    )
    metadata: dict[str, str | int | float | bool | None] = Field(
        default_factory=dict,
        description="Structured contextual attributes",
    )
    verdict: ThresholdEvaluationVerdict | None = Field(
        default=None,
        description="Dual threshold evaluation verdict if evaluated",
    )


class ScoreHonestyStats(BaseModel):
    """Aggregate diagnostics for retrieval score honesty and divergence."""

    total_candidates: int = Field(default=0, ge=0)
    admitted_count: int = Field(default=0, ge=0)
    rejected_count: int = Field(default=0, ge=0)
    raw_admitted_count: int = Field(default=0, ge=0)
    ranking_admitted_count: int = Field(default=0, ge=0)
    both_passed_count: int = Field(default=0, ge=0)
    divergence_count: int = Field(
        default=0,
        ge=0,
        description="Candidates where raw and ranking decisions disagree",
    )
    divergence_rate: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Ratio of diverging candidates over total candidates",
    )
    mean_raw_similarity: float = Field(default=0.0, ge=0.0, le=1.0)
    mean_ranking_score: float = Field(default=0.0, ge=0.0, le=1.0)
