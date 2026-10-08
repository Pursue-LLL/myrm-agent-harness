"""[POS]: tests/unit/toolkits/memory/test_lifecycle_hotness_suite.py
[INPUT]: Timestamp parameters, access frequencies, and simulated memory items.
[OUTPUT]: Pytest test cases verifying mathematical hotness precision, exponential decay, and blended reranking.
"""

from datetime import UTC, datetime, timedelta

import pytest

from myrm_agent_harness.toolkits.memory.lifecycle_hotness import (
    HotnessLifecycleStage,
    HotnessScoringConfig,
    MemoryHotnessScorer,
    MemoryLifecycleItem,
    compute_hotness_score,
)


def test_compute_hotness_score_math_properties() -> None:
    """Verify exact mathematical properties of the Sigmoid frequency and half-life decay formula."""
    now = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)

    # 1. Zero access, freshly updated (age = 0)
    # freq = 1 / (1 + exp(-log1p(0))) = 0.5, recency = 1.0 -> score = 0.5
    score_fresh = compute_hotness_score(active_count=0, updated_at=now, now=now, half_life_days=7.0)
    assert score_fresh == pytest.approx(0.5, rel=1e-3)

    # 2. Exactly one half-life elapsed (age = 7 days)
    # recency = exp(-(ln(2)/7) * 7) = 0.5 -> score = 0.5 * 0.5 = 0.25
    t_half_life = now - timedelta(days=7.0)
    score_half_life = compute_hotness_score(active_count=0, updated_at=t_half_life, now=now, half_life_days=7.0)
    assert score_half_life == pytest.approx(0.25, rel=1e-3)

    # 3. None updated_at must return 0.0
    assert compute_hotness_score(active_count=10, updated_at=None, now=now) == 0.0

    # 4. High frequency access freshly updated -> approaches 1.0
    score_high_freq = compute_hotness_score(active_count=100, updated_at=now, now=now)
    assert score_high_freq > 0.98


def test_lifecycle_classification_tiers() -> None:
    """Verify classification into COLD (<0.2), WARM (0.2-0.6), and HOT (>=0.6) tiers."""
    scorer = MemoryHotnessScorer(
        config=HotnessScoringConfig(
            cold_threshold=0.2,
            hot_threshold=0.6,
        )
    )

    assert scorer.classify(0.15) == HotnessLifecycleStage.COLD
    assert scorer.classify(0.35) == HotnessLifecycleStage.WARM
    assert scorer.classify(0.60) == HotnessLifecycleStage.HOT
    assert scorer.classify(0.95) == HotnessLifecycleStage.HOT


def test_blended_reranking_anti_stale() -> None:
    """Verify that recent active memories legitimately surpass stale historical memories with high semantic score."""
    now = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)
    scorer = MemoryHotnessScorer(
        config=HotnessScoringConfig(
            default_half_life_days=7.0,
            blend_alpha=0.3,  # 30% weight on hotness, 70% on semantic
            cold_threshold=0.2,
            hot_threshold=0.6,
        )
    )

    # Stale item: high semantic score (0.92) but 35 days untouched (5 half-lives)
    stale_item = MemoryLifecycleItem(
        id="mem://auth/legacy_basic_auth",
        active_count=1,
        updated_at=now - timedelta(days=35.0),
        semantic_score=0.92,
    )

    # Active fresh item: slightly lower semantic score (0.86) but used 20 times and updated 2 hours ago
    active_item = MemoryLifecycleItem(
        id="mem://auth/current_oauth_pkce",
        active_count=20,
        updated_at=now - timedelta(hours=2.0),
        semantic_score=0.86,
    )

    res = scorer.rerank_and_classify_batch([stale_item, active_item], now=now)

    assert len(res.items) == 2
    # Active item must rank 1st due to anti-stale hotness boost
    top_item = res.items[0]
    assert top_item.id == "mem://auth/current_oauth_pkce"
    assert top_item.lifecycle_stage == HotnessLifecycleStage.HOT
    assert top_item.blended_score > res.items[1].blended_score

    # Stale item should be marked COLD
    stale_evaluated = res.items[1]
    assert stale_evaluated.id == "mem://auth/legacy_basic_auth"
    assert stale_evaluated.lifecycle_stage == HotnessLifecycleStage.COLD

    # Batch summary verification
    assert res.hot_count == 1
    assert res.cold_count == 1
    assert res.warm_count == 0
    assert 0.0 < res.avg_hotness < 1.0
