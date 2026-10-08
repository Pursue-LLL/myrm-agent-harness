"""[POS]: src/myrm_agent_harness/toolkits/memory/lifecycle_hotness/calculator.py
[INPUT]: Active access counts, update timestamps, and hotness configurations.
[OUTPUT]: MemoryHotnessScorer implementation providing pure mathematical hotness calculation and lifecycle ranking.
"""

import math
from datetime import UTC, datetime

from .models import (
    BatchLifecycleClassificationResult,
    HotnessLifecycleStage,
    HotnessScoringConfig,
    MemoryLifecycleItem,
)


def compute_hotness_score(
    active_count: int,
    updated_at: datetime | None,
    now: datetime | None = None,
    half_life_days: float = 7.0,
) -> float:
    """Compute deterministic 0.0–1.0 hotness score based on access frequency and recency decay.

    Formula:
        score = sigmoid(log1p(active_count)) * exp(-(ln(2)/half_life_days) * age_days)
    """
    if now is None:
        now = datetime.now(UTC)

    # 1. Frequency component: Sigmoid projected log1p(active_count) -> [0.5, 1.0)
    safe_count = max(0, active_count)
    freq = 1.0 / (1.0 + math.exp(-math.log1p(safe_count)))

    # 2. Recency component: exponential time decay with half-life
    if updated_at is None:
        return 0.0

    # Ensure timezone aware UTC for deterministic elapsed calculation
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)

    age_days = max((now - updated_at).total_seconds() / 86400.0, 0.0)
    decay_rate = math.log(2) / max(0.001, half_life_days)
    recency = math.exp(-decay_rate * age_days)

    return float(max(0.0, min(1.0, freq * recency)))


class MemoryHotnessScorer:
    """Engine executing memory hotness scoring, semantic blending, and lifecycle classification."""

    def __init__(self, config: HotnessScoringConfig | None = None) -> None:
        self.config = config or HotnessScoringConfig()

    def score(
        self,
        active_count: int,
        updated_at: datetime | None,
        now: datetime | None = None,
    ) -> float:
        """Calculate pure hotness score using configured half-life."""
        return compute_hotness_score(
            active_count=active_count,
            updated_at=updated_at,
            now=now,
            half_life_days=self.config.default_half_life_days,
        )

    def blend(
        self,
        semantic_score: float,
        hotness_score: float,
        alpha: float | None = None,
    ) -> float:
        """Blend semantic similarity with hotness score: (1 - alpha)*semantic + alpha*hotness."""
        effective_alpha = self.config.blend_alpha if alpha is None else alpha
        effective_alpha = max(0.0, min(1.0, effective_alpha))
        return float((1.0 - effective_alpha) * semantic_score + effective_alpha * hotness_score)

    def classify(self, hotness: float) -> HotnessLifecycleStage:
        """Classify hotness score into COLD, WARM, or HOT lifecycle tier."""
        if hotness < self.config.cold_threshold:
            return HotnessLifecycleStage.COLD
        if hotness >= self.config.hot_threshold:
            return HotnessLifecycleStage.HOT
        return HotnessLifecycleStage.WARM

    def evaluate_item(
        self,
        item: MemoryLifecycleItem,
        now: datetime | None = None,
    ) -> MemoryLifecycleItem:
        """Evaluate and attach hotness, blended score, and lifecycle stage to a single item."""
        h_score = self.score(item.active_count, item.updated_at, now=now)
        b_score = self.blend(item.semantic_score, h_score)
        stage = self.classify(h_score)
        return item.model_copy(
            update={
                "hotness_score": h_score,
                "blended_score": b_score,
                "lifecycle_stage": stage,
            }
        )

    def rerank_and_classify_batch(
        self,
        items: list[MemoryLifecycleItem],
        now: datetime | None = None,
    ) -> BatchLifecycleClassificationResult:
        """Evaluate a batch of items, rerank by blended_score descending, and compute statistics."""
        if not items:
            return BatchLifecycleClassificationResult(
                items=[],
                cold_count=0,
                warm_count=0,
                hot_count=0,
                avg_hotness=0.0,
            )

        evaluated = [self.evaluate_item(item, now=now) for item in items]
        ranked = sorted(evaluated, key=lambda it: it.blended_score, reverse=True)

        cold_c = sum(1 for it in ranked if it.lifecycle_stage == HotnessLifecycleStage.COLD)
        warm_c = sum(1 for it in ranked if it.lifecycle_stage == HotnessLifecycleStage.WARM)
        hot_c = sum(1 for it in ranked if it.lifecycle_stage == HotnessLifecycleStage.HOT)
        avg_h = sum(it.hotness_score for it in ranked) / len(ranked)

        return BatchLifecycleClassificationResult(
            items=ranked,
            cold_count=cold_c,
            warm_count=warm_c,
            hot_count=hot_c,
            avg_hotness=float(avg_h),
        )
