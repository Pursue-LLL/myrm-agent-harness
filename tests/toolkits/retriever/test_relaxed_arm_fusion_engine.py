from __future__ import annotations

from myrm_agent_harness.toolkits.retriever import (
    AdaptiveReturnConfig,
    ArmCandidate,
    ArmKind,
    ArmNoiseDetector,
    RelaxedArmFusionEngine,
    RetrievalArm,
)


def test_arm_noise_detector_sharpness_and_flatness() -> None:
    """Test noise detection distinguishing sharp high-confidence arm from flat noisy arm."""
    config = AdaptiveReturnConfig(min_sharpness_gap=0.15)

    # Sharp arm: clear top-1 peak compared to long-tail average
    sharp_candidates = [
        ArmCandidate(item={"title": "Target Bugfix"}, key="doc_1", score=0.95, rank=1),
        ArmCandidate(item={"title": "Related"}, key="doc_2", score=0.40, rank=2),
        ArmCandidate(item={"title": "Vague"}, key="doc_3", score=0.20, rank=3),
    ]
    sharp_arm = RetrievalArm(name="vector_lane", arm_kind=ArmKind.VECTOR, candidates=sharp_candidates)
    is_demoted_sharp, peak_s, _mean_s, gap_s, _ = ArmNoiseDetector.evaluate_arm(sharp_arm, config)
    assert is_demoted_sharp is False
    assert peak_s == 0.95
    assert gap_s > 0.15

    # Flat noisy arm: all candidates have virtually identical mediocre scores
    flat_candidates = [
        ArmCandidate(item={"title": "Common Word A"}, key="noise_1", score=0.51, rank=1),
        ArmCandidate(item={"title": "Common Word B"}, key="noise_2", score=0.50, rank=2),
        ArmCandidate(item={"title": "Common Word C"}, key="noise_3", score=0.49, rank=3),
        ArmCandidate(item={"title": "Common Word D"}, key="noise_4", score=0.48, rank=4),
    ]
    noisy_arm = RetrievalArm(name="bm25_generic", arm_kind=ArmKind.BM25, candidates=flat_candidates)
    is_demoted_noisy, _peak_n, _mean_n, gap_n, _ = ArmNoiseDetector.evaluate_arm(noisy_arm, config)
    assert is_demoted_noisy is True
    assert gap_n < 0.15


def test_noisy_bm25_demotion_preserves_sharp_vector_top_ranks() -> None:
    """Benchmark test mimicking gbrain PR #4787: noisy arm demotion protects gold candidates."""
    config = AdaptiveReturnConfig(
        target_top_k=5,
        min_core_items=2,
        min_sharpness_gap=0.15,
        demotion_factor=0.20,
    )
    engine = RelaxedArmFusionEngine[dict[str, str]](config=config)

    # High precision vector arm
    vector_candidates = [
        ArmCandidate(item={"title": "Gold Solution 1"}, key="gold_1", score=0.98, rank=1),
        ArmCandidate(item={"title": "Gold Solution 2"}, key="gold_2", score=0.92, rank=2),
        ArmCandidate(item={"title": "Irrelevant"}, key="irr_v", score=0.10, rank=3),
    ]
    vector_arm = RetrievalArm(name="vector_arm", arm_kind=ArmKind.VECTOR, candidates=vector_candidates)

    # Noisy BM25 arm filled with common token hits
    bm25_candidates = [
        ArmCandidate(item={"title": f"Noisy Hit {i}"}, key=f"noise_{i}", score=0.45 - i * 0.005, rank=i)
        for i in range(1, 8)
    ]
    bm25_arm = RetrievalArm(name="bm25_arm", arm_kind=ArmKind.BM25, candidates=bm25_candidates)

    result = engine.fuse([vector_arm, bm25_arm])

    # Verification:
    # 1. BM25 was demoted
    assert "bm25_arm" in result.demoted_arms
    assert "vector_arm" not in result.demoted_arms

    # 2. Gold candidates remain at top-1 and top-2
    assert len(result.hits) >= 2
    assert result.hits[0].key == "gold_1"
    assert result.hits[1].key == "gold_2"
    assert result.hits[0].score >= result.hits[1].score


def test_volunteer_arm_dynamic_activation_when_core_insufficient() -> None:
    """Test dynamic activation of volunteer arm when core arms fail to yield enough hits."""
    config = AdaptiveReturnConfig(
        target_top_k=5,
        min_core_items=4,  # Expect at least 4 items from core
        volunteer_boost=1.2,
    )
    engine = RelaxedArmFusionEngine[str](config=config)

    # Core arm only has 2 candidates
    core_candidates = [
        ArmCandidate(item="Core A", key="core_a", score=0.88, rank=1),
        ArmCandidate(item="Core B", key="core_b", score=0.82, rank=2),
    ]
    core_arm = RetrievalArm(name="core_vector", arm_kind=ArmKind.VECTOR, candidates=core_candidates)

    # Volunteer arm (e.g. historical context memory fallback)
    volunteer_candidates = [
        ArmCandidate(item="Volunteer C", key="vol_c", score=0.75, rank=1),
        ArmCandidate(item="Volunteer D", key="vol_d", score=0.70, rank=2),
        ArmCandidate(item="Volunteer E", key="vol_e", score=0.65, rank=3),
    ]
    vol_arm = RetrievalArm(
        name="volunteer_archive",
        arm_kind=ArmKind.VOLUNTEER,
        candidates=volunteer_candidates,
        is_volunteer=True,
    )

    result = engine.fuse([core_arm, vol_arm])

    # Core items (2) < min_core_items (4) => volunteer channel activated
    assert result.volunteer_activated is True
    keys = [hit.key for hit in result.hits]
    assert "core_a" in keys
    assert "core_b" in keys
    assert "vol_c" in keys
    assert "vol_d" in keys

    # Check volunteer fallback flag on volunteer-only items
    vol_hit = next(hit for hit in result.hits if hit.key == "vol_c")
    assert vol_hit.is_volunteer_fallback is True


def test_volunteer_arm_dormant_when_core_is_sufficient() -> None:
    """Verify that volunteer arm remains dormant when core arms return sufficient candidates."""
    config = AdaptiveReturnConfig(
        target_top_k=4,
        min_core_items=3,
    )
    engine = RelaxedArmFusionEngine[str](config=config)

    core_candidates = [
        ArmCandidate(item=f"Core {i}", key=f"core_{i}", score=0.80, rank=i)
        for i in range(1, 5)
    ]
    core_arm = RetrievalArm(name="core_vector", arm_kind=ArmKind.VECTOR, candidates=core_candidates)

    vol_candidates = [
        ArmCandidate(item="Vol 1", key="vol_1", score=0.99, rank=1),
    ]
    vol_arm = RetrievalArm(name="vol_arm", arm_kind=ArmKind.VOLUNTEER, candidates=vol_candidates, is_volunteer=True)

    result = engine.fuse([core_arm, vol_arm])
    assert result.volunteer_activated is False
    assert not any(hit.key == "vol_1" for hit in result.hits)


def test_telemetry_profiles_and_empty_edge_cases() -> None:
    """Test telemetry completeness and graceful degradation on empty inputs."""
    engine = RelaxedArmFusionEngine[str]()

    # Empty inputs
    empty_res = engine.fuse([])
    assert empty_res.hits == []
    assert empty_res.arm_telemetry == []
    assert empty_res.volunteer_activated is False

    # Arm with no candidates
    empty_arm = RetrievalArm(name="empty_lane", arm_kind=ArmKind.CODE_AST, candidates=[])
    res2 = engine.fuse([empty_arm])
    assert res2.hits == []
    assert len(res2.arm_telemetry) == 1
    assert res2.arm_telemetry[0].raw_count == 0
