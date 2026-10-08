"""Unit tests for retrieval score honesty suite, models, and dual-threshold pipeline."""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.score_honesty.facade import RetrievalScoreHonestySuite
from myrm_agent_harness.toolkits.memory.score_honesty.models import (
    DualThresholdConfig,
    RejectionStage,
    ScoreBreakdown,
    ScoreHonestyStats,
)
from myrm_agent_harness.toolkits.memory.score_honesty.pipeline import ScoreHonestyPipeline
from myrm_agent_harness.toolkits.memory.types import (
    MemorySearchResult,
    MemoryType,
    SemanticMemory,
)


def test_score_breakdown_computation() -> None:
    pipeline = ScoreHonestyPipeline()

    # Case 1: Standard computation
    bd = pipeline.compute_breakdown(
        raw_similarity=0.8,
        recency_factor=1.1,
        importance_boost=1.0,
        mmr_penalty=0.1,
        rrf_score=0.02,
    )
    assert 0.0 <= bd.final_ranking_score <= 1.0
    assert bd.raw_similarity == 0.8
    assert bd.recency_factor == 1.1
    assert bd.mmr_penalty == 0.1
    assert "raw=0.800" in bd.explanation

    # Case 2: Extreme values clamped safely
    bd_extreme = pipeline.compute_breakdown(
        raw_similarity=2.5,  # clamped to 1.0
        recency_factor=-0.5,  # clamped to 0.0
        importance_boost=3.0,  # clamped to 2.0
        mmr_penalty=5.0,  # clamped to 1.0
        rrf_score=-1.0,  # clamped to 0.0
    )
    assert bd_extreme.raw_similarity == 1.0
    assert bd_extreme.recency_factor == 0.0
    assert bd_extreme.importance_boost == 2.0
    assert bd_extreme.mmr_penalty == 1.0
    assert bd_extreme.final_ranking_score == 0.0


def test_dual_threshold_evaluation_strict_mode() -> None:
    pipeline = ScoreHonestyPipeline()
    config = DualThresholdConfig(
        raw_similarity_threshold=0.6,
        ranking_score_threshold=0.5,
        strict_mode=True,
    )

    # Both passed
    v1 = pipeline.evaluate_verdict(raw_similarity=0.7, ranking_score=0.6, config=config)
    assert v1.admitted is True
    assert v1.passed_raw is True
    assert v1.passed_ranking is True
    assert v1.rejection_stage == RejectionStage.NONE

    # Passed raw, failed ranking
    v2 = pipeline.evaluate_verdict(raw_similarity=0.7, ranking_score=0.4, config=config)
    assert v2.admitted is False
    assert v2.passed_raw is True
    assert v2.passed_ranking is False
    assert v2.rejection_stage == RejectionStage.RANKING_BELOW_THRESHOLD
    assert v2.rejection_reason is not None

    # Failed raw, passed ranking (artificial score inflation)
    v3 = pipeline.evaluate_verdict(raw_similarity=0.4, ranking_score=0.8, config=config)
    assert v3.admitted is False
    assert v3.passed_raw is False
    assert v3.passed_ranking is True
    assert v3.rejection_stage == RejectionStage.RAW_BELOW_THRESHOLD
    assert v3.rejection_reason is not None

    # Both failed
    v4 = pipeline.evaluate_verdict(raw_similarity=0.2, ranking_score=0.1, config=config)
    assert v4.admitted is False
    assert v4.passed_raw is False
    assert v4.passed_ranking is False
    assert v4.rejection_stage == RejectionStage.BOTH_BELOW_THRESHOLD


def test_dual_threshold_evaluation_lenient_mode() -> None:
    pipeline = ScoreHonestyPipeline()
    config = DualThresholdConfig(
        raw_similarity_threshold=0.6,
        ranking_score_threshold=0.5,
        strict_mode=False,
    )

    # Failed raw, passed ranking admitted in lenient mode
    v = pipeline.evaluate_verdict(raw_similarity=0.4, ranking_score=0.8, config=config)
    assert v.admitted is True
    assert v.passed_raw is False
    assert v.passed_ranking is True
    assert v.rejection_stage == RejectionStage.RAW_BELOW_THRESHOLD


def test_suite_evaluate_and_divergence_diagnostics() -> None:
    suite = RetrievalScoreHonestySuite()
    c1 = suite.create_candidate("mem-1", "Authentication secrets", raw_similarity=0.85, recency_factor=1.2)
    c2 = suite.create_candidate("mem-2", "Old docker notes", raw_similarity=0.75, recency_factor=0.3)
    c3 = suite.create_candidate("mem-3", "Recent irrelevant log", raw_similarity=0.25, recency_factor=1.8)

    cfg = DualThresholdConfig(raw_similarity_threshold=0.5, ranking_score_threshold=0.5, strict_mode=True)
    evaluated, stats = suite.evaluate([c1, c2, c3], config=cfg)

    assert len(evaluated) == 3
    # Check stable descending ordering by ranking_score
    assert evaluated[0].ranking_score >= evaluated[1].ranking_score >= evaluated[2].ranking_score
    assert isinstance(stats, ScoreHonestyStats)
    assert stats.total_candidates == 3
    assert stats.divergence_count >= 1
    assert 0.0 < stats.divergence_rate <= 1.0

    # Test filtering admitted only
    admitted = suite.filter_admitted([c1, c2, c3], config=cfg)
    assert all(c.verdict.admitted for c in admitted if c.verdict)

    # Test divergence filter
    divergent = suite.diagnose_divergence([c1, c2, c3], config=cfg)
    assert len(divergent) == stats.divergence_count

    # Explanation test
    explanation = suite.explain_candidate(c1)
    assert "mem-1" in explanation
    assert "raw_similarity" in explanation


def test_memory_search_result_extended_honesty_fields() -> None:
    memory = SemanticMemory(content="Postgres connection timeout resolution", domain="task")
    bd = ScoreBreakdown(
        raw_similarity=0.92,
        recency_factor=1.0,
        importance_boost=1.1,
        mmr_penalty=0.0,
        rrf_score=0.01,
        final_ranking_score=0.88,
        explanation="Test breakdown",
    )

    res = MemorySearchResult(
        memory=memory,
        score=0.88,
        raw_similarity=0.92,
        ranking_score=0.88,
        score_breakdown=bd,
        memory_type=MemoryType.SEMANTIC,
    )

    assert res.score == 0.88
    assert res.raw_similarity == 0.92
    assert res.ranking_score == 0.88
    assert res.score_breakdown is not None
    assert res.score_breakdown.raw_similarity == 0.92
    assert res.id == memory.id
    assert res.content == "Postgres connection timeout resolution"
