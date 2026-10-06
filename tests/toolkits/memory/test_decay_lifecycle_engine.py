# [INPUT] EbbinghausDecayScorer, TieredStorageLifecycleManager, and DecayAwareReranker.
# [OUTPUT] Pytest suite verifying exponential decay, RFM frequency boosts, tiered migration, and reranking.
# [POS] tests.toolkits.memory.test_decay_lifecycle_engine

"""Unit tests for Ebbinghaus temporal decay and tiered storage lifecycle engine."""

import time

import pytest

from myrm_agent_harness.toolkits.memory.decay.lifecycle_manager import (
    TieredStorageLifecycleManager,
)
from myrm_agent_harness.toolkits.memory.decay.reranker import (
    DecayAwareReranker,
)
from myrm_agent_harness.toolkits.memory.decay.scorer import (
    EbbinghausDecayScorer,
)
from myrm_agent_harness.toolkits.memory.decay.types import (
    DecayScorerConfig,
    MemoryDecayProfile,
    StorageTier,
)


@pytest.fixture
def scorer() -> EbbinghausDecayScorer:
    config = DecayScorerConfig(
        lambda_decay=0.05,
        alpha_freq=0.3,
        hot_threshold=0.6,
        cold_threshold=0.2,
        cold_min_age_days=30.0,
    )
    return EbbinghausDecayScorer(config=config)


@pytest.fixture
def lifecycle_manager(scorer: EbbinghausDecayScorer) -> TieredStorageLifecycleManager:
    return TieredStorageLifecycleManager(scorer=scorer)


def test_ebbinghaus_decay_scorer_fresh_and_decayed(scorer: EbbinghausDecayScorer) -> None:
    """Verify exponential retention decay over 0, 30, and 60 days."""
    t0 = 1000000.0
    profile = MemoryDecayProfile(
        memory_id="mem-1",
        content="Temporary bug fix parameter",
        importance=0.7,
        created_at=t0,
        last_accessed_at=t0,
        access_count=0,
    )

    # Day 0: fresh memory
    score_day0, tier_day0 = scorer.calculate_score(profile, current_time=t0)
    assert score_day0 >= 0.6
    assert tier_day0 == StorageTier.HOT

    # Day 14: elapsed 14 days (half-life) without touch
    t14 = t0 + 14 * 86400.0
    score_day14, tier_day14 = scorer.calculate_score(profile, current_time=t14)
    assert score_day14 < score_day0
    assert tier_day14 == StorageTier.WARM

    # Day 60: elapsed 60 days
    t60 = t0 + 60 * 86400.0
    score_day60, tier_day60 = scorer.calculate_score(profile, current_time=t60)
    assert score_day60 < 0.2
    assert tier_day60 == StorageTier.COLD


def test_rfm_frequency_reinforcement(scorer: EbbinghausDecayScorer) -> None:
    """Verify that high access frequency counteracts temporal decay."""
    t0 = 1000000.0
    t30 = t0 + 30 * 86400.0

    # Low frequency profile (accessed 0 times after creation)
    profile_dormant = MemoryDecayProfile(
        memory_id="mem-dormant",
        content="Dormant note",
        importance=0.8,
        created_at=t0,
        last_accessed_at=t0,
        access_count=0,
    )

    # High frequency profile (accessed 12 times)
    profile_frequent = MemoryDecayProfile(
        memory_id="mem-frequent",
        content="Core architectural guideline",
        importance=0.8,
        created_at=t0,
        last_accessed_at=t0,
        access_count=12,
    )

    score_dormant, _tier_dormant = scorer.calculate_score(profile_dormant, current_time=t30)
    score_frequent, tier_frequent = scorer.calculate_score(profile_frequent, current_time=t30)

    assert score_frequent > score_dormant
    assert tier_frequent in (StorageTier.HOT, StorageTier.WARM)


def test_pinned_memory_never_decays(scorer: EbbinghausDecayScorer) -> None:
    """Verify that pinned memories retain maximum score regardless of time elapsed."""
    t0 = 1000000.0
    t365 = t0 + 365 * 86400.0

    profile = MemoryDecayProfile(
        memory_id="mem-pinned",
        content="User core persona profile",
        importance=1.0,
        created_at=t0,
        last_accessed_at=t0,
        access_count=1,
        pinned=True,
    )

    score, tier = scorer.calculate_score(profile, current_time=t365)
    assert score == 1.0
    assert tier == StorageTier.HOT


def test_tiered_lifecycle_evaluate_and_migrate(
    lifecycle_manager: TieredStorageLifecycleManager,
) -> None:
    """Verify batch evaluation and bucket migration across hot, warm, and cold tiers."""
    t0 = time.time()
    day_sec = 86400.0

    # Register 3 memories at different historical times
    lifecycle_manager.register_memory("mem-fresh", "Fresh note", 0.9, created_at=t0)
    lifecycle_manager.register_memory("mem-warm", "Month old note", 0.6, created_at=t0 - 20 * day_sec)
    lifecycle_manager.register_memory("mem-old", "Quarter old note", 0.3, created_at=t0 - 70 * day_sec)

    report = lifecycle_manager.evaluate_and_migrate(current_time=t0)

    assert report.total_evaluated == 3
    assert report.hot_count >= 1
    assert report.cold_count >= 1
    assert len(report.migrated_memory_ids) >= 1

    cold_profiles = lifecycle_manager.get_profiles_by_tier(StorageTier.COLD)
    assert any(p.memory_id == "mem-old" for p in cold_profiles)


def test_revive_cold_memory(lifecycle_manager: TieredStorageLifecycleManager) -> None:
    """Verify revicing cold memory boosts its tier back to HOT."""
    t0 = time.time()
    day_sec = 86400.0

    # Create an old cold memory
    lifecycle_manager.register_memory("mem-to-revive", "Old secret key", 0.3, created_at=t0 - 90 * day_sec)
    lifecycle_manager.evaluate_and_migrate(current_time=t0)

    assert any(p.memory_id == "mem-to-revive" for p in lifecycle_manager.get_profiles_by_tier(StorageTier.COLD))

    # Revive memory
    revived = lifecycle_manager.revive_memory("mem-to-revive", boost_importance=0.9, current_time=t0)
    assert revived is not None
    assert revived.current_tier == StorageTier.HOT
    assert revived.importance == 0.9

    hot_profiles = lifecycle_manager.get_profiles_by_tier(StorageTier.HOT)
    assert any(p.memory_id == "mem-to-revive" for p in hot_profiles)


def test_decay_aware_reranker(lifecycle_manager: TieredStorageLifecycleManager) -> None:
    """Verify decay-aware reranking pushes decayed candidates down and keeps active items top."""
    t0 = time.time()
    day_sec = 86400.0

    # Register one high-importance fresh memory, and one older memory with slightly higher similarity
    lifecycle_manager.register_memory("mem-active", "Active guideline", 0.9, created_at=t0)
    lifecycle_manager.register_memory("mem-stale", "Stale snippet", 0.4, created_at=t0 - 45 * day_sec)
    lifecycle_manager.evaluate_and_migrate(current_time=t0)

    reranker = DecayAwareReranker(lifecycle_manager=lifecycle_manager, decay_weight=0.5)

    candidates = [
        ("mem-stale", "Stale snippet", 0.85),
        ("mem-active", "Active guideline", 0.80),
    ]

    reranked = reranker.rerank(candidates, exclude_cold=False, current_time=t0)
    assert len(reranked) == 2
    # mem-active should overtake mem-stale due to decay weighting
    assert reranked[0].memory_id == "mem-active"
    assert reranked[1].memory_id == "mem-stale"


def test_export_cold_archive(lifecycle_manager: TieredStorageLifecycleManager) -> None:
    """Verify exporting cold memories produces serialized archive records."""
    t0 = time.time()
    day_sec = 86400.0

    lifecycle_manager.register_memory("mem-archive-1", "Deprecated config", 0.2, created_at=t0 - 60 * day_sec)
    lifecycle_manager.evaluate_and_migrate(current_time=t0)

    records = lifecycle_manager.export_cold_archive()
    assert len(records) >= 1
    record = records[0]
    assert record["memory_id"] == "mem-archive-1"
    assert record["tier"] == "COLD"
    assert "score" in record
