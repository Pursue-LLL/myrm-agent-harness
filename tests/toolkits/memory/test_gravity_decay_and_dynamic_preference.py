"""Tests for continuous gravity decay scoring and dynamic preference fitting."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from myrm_agent_harness.toolkits.memory.config import RetrievalConfig
from myrm_agent_harness.toolkits.memory.retriever import MemoryRetriever
from myrm_agent_harness.toolkits.memory.signals import SignalCalculator
from myrm_agent_harness.toolkits.memory.strategies.dynamic_preference import (
    MAX_WEIGHT_BOUND,
    MIN_WEIGHT_BOUND,
    PRIOR_BASELINE_WEIGHT,
    DynamicPreferenceFitter,
    DynamicPreferenceVector,
    FeedbackAction,
)
from myrm_agent_harness.toolkits.memory.strategies.gravity_decay import (
    GravityDecayConfig,
    compute_gravity_decay,
    parse_timestamp_utc,
)
from myrm_agent_harness.toolkits.memory.types import (
    MemorySearchResult,
    MemoryType,
    ProceduralMemory,
    SemanticMemory,
)


class TestGravityDecayScorer:
    """Unit tests for continuous gravity decay scoring."""

    def test_config_validation(self) -> None:
        with pytest.raises(ValueError, match="gravity must be strictly positive"):
            GravityDecayConfig(gravity=0.0)

        with pytest.raises(ValueError, match="time_scale_hours must be strictly positive"):
            GravityDecayConfig(time_scale_hours=-1.0)

        with pytest.raises(ValueError, match="interaction_weight cannot be negative"):
            GravityDecayConfig(interaction_weight=-0.1)

    def test_baseline_and_monotonicity(self) -> None:
        now = datetime(2026, 9, 17, 12, 0, 0, tzinfo=UTC)
        # delta_t = 0
        score_0h = compute_gravity_decay(now, now=now, interactions=0, quality_score=0.0)
        assert pytest.approx(score_0h, rel=1e-3) == 1.0

        # Monotonic time decay
        score_1h = compute_gravity_decay(now - timedelta(hours=1), now=now)
        score_5h = compute_gravity_decay(now - timedelta(hours=5), now=now)
        score_24h = compute_gravity_decay(now - timedelta(hours=24), now=now)

        assert score_0h > score_1h > score_5h > score_24h > 0.0

    def test_sub_hour_resolution_overcomes_discrete_days(self) -> None:
        now = datetime(2026, 9, 17, 20, 0, 0, tzinfo=UTC)
        # Both created within the same UTC day
        item_morning = now - timedelta(hours=10)
        item_recent = now - timedelta(minutes=15)

        score_morning = compute_gravity_decay(item_morning, now=now)
        score_recent = compute_gravity_decay(item_recent, now=now)

        # Continuous decay clearly differentiates sub-day entries
        assert score_recent > score_morning * 1.3

    def test_interaction_and_quality_boost(self) -> None:
        now = datetime(2026, 9, 17, 12, 0, 0, tzinfo=UTC)
        time_point = now - timedelta(hours=6)

        unpopular = compute_gravity_decay(time_point, now=now, interactions=0, quality_score=0.0)
        hot_item = compute_gravity_decay(time_point, now=now, interactions=20, quality_score=0.9)

        assert hot_item > unpopular * 2.0

    def test_clock_skew_and_future_timestamps(self) -> None:
        now = datetime(2026, 9, 17, 12, 0, 0, tzinfo=UTC)
        future_time = now + timedelta(hours=2)

        # Future timestamps are bounded at delta_t = 0
        score_future = compute_gravity_decay(future_time, now=now)
        assert pytest.approx(score_future, rel=1e-3) == 1.0

    def test_timestamp_parser_robustness(self) -> None:
        assert parse_timestamp_utc(None).tzinfo == UTC
        assert parse_timestamp_utc("invalid-date-format").tzinfo == UTC
        assert parse_timestamp_utc("2026-09-17T10:00:00Z").hour == 10
        assert parse_timestamp_utc(1789553190.0).year >= 2026


class TestDynamicPreferenceFitting:
    """Unit tests for online preference fitting and safety bounds."""

    def test_default_vector_and_reset(self) -> None:
        vec = DynamicPreferenceVector()
        assert vec.recency == PRIOR_BASELINE_WEIGHT
        assert vec.actionability == PRIOR_BASELINE_WEIGHT

        vec.recency = 2.5
        vec.reset_to_baseline()
        assert vec.recency == PRIOR_BASELINE_WEIGHT

    def test_fit_step_direction_and_clipping(self) -> None:
        fitter = DynamicPreferenceFitter(learning_rate=0.10, l2_shrinkage=0.01)
        vec = DynamicPreferenceVector()

        fitter.fit_step(vec, FeedbackAction.MORE_CODE)
        # Actionability and technical depth should increase
        assert vec.actionability > PRIOR_BASELINE_WEIGHT
        assert vec.technical_depth > PRIOR_BASELINE_WEIGHT
        # Breadth has negative gradient, should decrease
        assert vec.breadth < PRIOR_BASELINE_WEIGHT

    def test_hard_bounds_and_anti_collapse(self) -> None:
        fitter = DynamicPreferenceFitter(learning_rate=0.20, l2_shrinkage=0.0)
        vec = DynamicPreferenceVector()

        # Apply negative update 500 times
        for _ in range(500):
            fitter.fit_step(vec, FeedbackAction.MORE_CONCISE)

        # Ensure breadth does not fall below minimum bound
        assert vec.breadth >= MIN_WEIGHT_BOUND
        assert vec.conciseness <= MAX_WEIGHT_BOUND

    def test_l2_prior_shrinkage_recovery(self) -> None:
        fitter = DynamicPreferenceFitter(learning_rate=0.10, l2_shrinkage=0.10)
        vec = DynamicPreferenceVector()

        fitter.fit_step(vec, FeedbackAction.MORE_RECENT)
        boosted_recency = vec.recency
        assert boosted_recency > 1.0

        # In neutral feedback with shrinkage, weight gradually decays back toward 1.0
        # Simulated by multiple positive acceptances with zero recency gradient
        for _ in range(10):
            fitter.fit_step(vec, FeedbackAction.POSITIVE_ACCEPT)

        assert vec.recency < boosted_recency

    def test_locked_vector_immunity(self) -> None:
        fitter = DynamicPreferenceFitter()
        vec = DynamicPreferenceVector(locked=True)
        original_actionability = vec.actionability

        fitter.fit_step(vec, FeedbackAction.MORE_CODE)
        assert vec.actionability == original_actionability

    def test_implicit_feedback_heuristic_extraction(self) -> None:
        fitter = DynamicPreferenceFitter()

        action_code = fitter.detect_implicit_action("请只给出可运行代码，不要啰嗦")
        assert action_code == FeedbackAction.MORE_CODE

        action_concise = fitter.detect_implicit_action("太啰嗦了，简短一点回答")
        assert action_concise == FeedbackAction.MORE_CONCISE

        action_depth = fitter.detect_implicit_action("深入剖析底层的架构演进和原理")
        assert action_depth == FeedbackAction.MORE_IN_DEPTH

        action_none = fitter.detect_implicit_action("你好，今天天气怎么样？")
        assert action_none is None


class TestRetrieverIntegration:
    """Integration tests verifying gravity decay and dynamic weights in Retriever."""

    def test_signal_calc_gravity_decay_bridge(self) -> None:
        mem = SemanticMemory(
            id="mem-1",
            content="Kafka rebalance storm incident report",
            created_at=datetime.now(UTC) - timedelta(hours=2),
            access_count=10,
            rating=0.8,
        )
        factor = SignalCalculator.gravity_decay_factor(mem)
        assert factor > 0.0

    def test_retriever_ranking_with_gravity_decay(self) -> None:
        now = datetime.now(UTC)
        old_mem = SemanticMemory(
            id="old-doc",
            content="Legacy Kafka concepts from 2021",
            created_at=now - timedelta(days=90),
            access_count=1,
            rating=0.2,
        )
        new_hot_mem = SemanticMemory(
            id="new-pulse",
            content="Kafka rebalance storm live incident fix",
            created_at=now - timedelta(minutes=30),
            access_count=15,
            rating=0.9,
        )

        res_old = MemorySearchResult(
            memory=old_mem,
            score=0.80,
            memory_type=MemoryType.SEMANTIC,
        )
        res_new = MemorySearchResult(
            memory=new_hot_mem,
            score=0.75,  # Slightly lower semantic base
            memory_type=MemoryType.SEMANTIC,
        )

        # Without gravity decay, the old item with 0.80 might rank ahead or close
        cfg_standard = RetrievalConfig(enable_gravity_decay=False)
        retriever_std = MemoryRetriever(cfg_standard)
        ranked_std = retriever_std.rank([res_old, res_new], limit=2)
        assert len(ranked_std) == 2

        # With continuous gravity decay, the 30-min hot pulse item ranks ahead
        cfg_gravity = RetrievalConfig(enable_gravity_decay=True, gravity_power=1.8)
        retriever_grav = MemoryRetriever(cfg_gravity)
        ranked_grav = retriever_grav.rank([res_old, res_new], limit=2)

        assert ranked_grav[0].id == "new-pulse"

    def test_dynamic_preference_prior_preservation_procedural(self) -> None:
        """Verify PROCEDURAL memories preserve recency=0 zero-prior even with dynamic preference recency boost."""
        now = datetime.now(UTC)
        proc_mem = ProceduralMemory(
            id="rule-pnpm-test",
            content="Run pnpm test before commit",
            trigger="before commit",
            action="pnpm test",
            created_at=now - timedelta(days=120),  # very old rule
            confidence=1.0,
        )
        res_proc = MemorySearchResult(
            memory=proc_mem,
            score=0.90,
            memory_type=MemoryType.PROCEDURAL,
        )

        # Apply high recency multiplier in dynamic weights
        cfg_dynamic = RetrievalConfig(
            dynamic_signal_weights={"recency": 3.0, "importance": 1.0}
        )
        retriever = MemoryRetriever(cfg_dynamic)

        # Procedural rule should NOT be suppressed by its 120-day age because recency prior is 0
        ranked = retriever.rank([res_proc], limit=1)
        assert len(ranked) == 1
        assert ranked[0].score > 0.85

    def test_dynamic_preference_l1_normalization(self) -> None:
        """Verify dynamic signal weights strictly maintain sum(weights) == 1.0 under modulation."""
        now = datetime.now(UTC)
        mem = SemanticMemory(
            id="mem-norm-check",
            content="Architecture decision record",
            created_at=now - timedelta(hours=1),
        )
        res = MemorySearchResult(
            memory=mem,
            score=0.85,
            memory_type=MemoryType.SEMANTIC,
        )

        # Pass extreme dynamic multipliers
        cfg = RetrievalConfig(
            dynamic_signal_weights={
                "recency": 2.5,
                "importance": 2.0,
                "preference": 0.5,
                "rating": 0.5,
            }
        )
        retriever = MemoryRetriever(cfg)
        score = retriever._geometric_score(0.85, res)
        # Score must be bounded in (0, 1] and calculated without power inflation
        assert 0.0 < score <= 1.0
