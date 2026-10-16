"""Tests for SkillForgettingStrategy."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from myrm_agent_harness.backends.skills.curator_config import CuratorConfig
from myrm_agent_harness.backends.skills.forgetting_strategy import (
    DefaultForgettingStrategy,
    ForgettingReason,
    evaluate_skill_health_findings,
)
from myrm_agent_harness.backends.skills.types import (
    SkillLifecycleStatus,
    SkillMetadata,
    SkillUsageStats,
)


def create_skill_metadata(name: str, usage_stats: SkillUsageStats | None = None) -> SkillMetadata:
    """Helper to create SkillMetadata for testing."""
    skill = SkillMetadata(name=name, description="Test skill")
    if usage_stats:
        object.__setattr__(skill, "usage_stats", usage_stats)
    return skill


def test_should_forget_stale_skill() -> None:
    """Test that never-used skills past stale threshold are marked for forgetting."""
    config = CuratorConfig(stale_after_days=30)
    strategy = DefaultForgettingStrategy(config)

    old_created = datetime.now(UTC) - timedelta(days=60)
    stats = SkillUsageStats(call_count=0, success_count=0, failure_count=0, created_at=old_created)
    skill = create_skill_metadata("stale_skill", usage_stats=stats)
    reason = strategy.should_forget(skill)

    assert reason is not None
    assert reason.reason_type == "stale"


def test_should_not_forget_never_used_within_stale_threshold() -> None:
    """Never-used skills younger than stale_after_days must not be marked stale."""
    config = CuratorConfig(stale_after_days=30, grace_period_days=0)
    strategy = DefaultForgettingStrategy(config)

    recent_created = datetime.now(UTC) - timedelta(days=5)
    stats = SkillUsageStats(call_count=0, success_count=0, failure_count=0, created_at=recent_created)
    skill = create_skill_metadata("young_skill", usage_stats=stats)
    assert strategy.should_forget(skill) is None


def test_protect_system_skills_exempt() -> None:
    """Prebuilt skills under /prebuilt/ are exempt when protect_system_skills is True."""
    config = CuratorConfig(stale_after_days=7, protect_system_skills=True, grace_period_days=0)
    strategy = DefaultForgettingStrategy(config)

    old_created = datetime.now(UTC) - timedelta(days=100)
    stats = SkillUsageStats(call_count=0, success_count=0, failure_count=0, created_at=old_created)
    skill = SkillMetadata(
        name="prebuilt_skill",
        description="Test skill",
        storage_path="/opt/myrm/assets/prebuilt/foo_skill",
        usage_stats=stats,
    )
    assert strategy.should_forget(skill) is None


def test_should_forget_low_quality_skill() -> None:
    """Test that low quality skills are marked for forgetting."""
    config = CuratorConfig(min_call_count_for_quality_check=5, min_success_rate=0.5)
    strategy = DefaultForgettingStrategy(config)

    # Skill with low success rate
    stats = SkillUsageStats(
        call_count=10,
        success_count=2,
        failure_count=8,
        last_used_at=datetime.now(UTC),
    )
    skill = create_skill_metadata("low_quality_skill", usage_stats=stats)
    reason = strategy.should_forget(skill)

    assert reason is not None
    assert reason.reason_type == "low_quality"
    assert ("20" in reason.reason_message or "0.2" in reason.reason_message) and "%" in reason.reason_message


def test_should_not_forget_high_quality_skill() -> None:
    """Test that high quality skills are not forgotten."""
    config = CuratorConfig(stale_after_days=30)
    strategy = DefaultForgettingStrategy(config)

    # Skill with high success rate and recent usage
    stats = SkillUsageStats(
        call_count=10,
        success_count=9,
        failure_count=1,
        last_used_at=datetime.now(UTC),
    )
    skill = create_skill_metadata("good_skill", usage_stats=stats)
    reason = strategy.should_forget(skill)

    assert reason is None


def test_should_forget_inactive_skill() -> None:
    """Test that inactive skills are marked for forgetting."""
    config = CuratorConfig(stale_after_days=30)
    strategy = DefaultForgettingStrategy(config)

    # Skill used long ago
    old_date = datetime.now(UTC) - timedelta(days=60)
    stats = SkillUsageStats(
        call_count=10,
        success_count=8,
        failure_count=2,
        last_used_at=old_date,
    )
    skill = create_skill_metadata("inactive_skill", usage_stats=stats)
    reason = strategy.should_forget(skill)

    assert reason is not None
    assert reason.reason_type == "inactive"
    assert "60" in reason.reason_message or "inactive" in reason.reason_message.lower()


def test_low_quality_threshold_not_met() -> None:
    """Test that skills with few calls are not judged by quality."""
    config = CuratorConfig(min_call_count_for_quality_check=10, min_success_rate=0.5)
    strategy = DefaultForgettingStrategy(config)

    # Skill with low success rate but few calls
    stats = SkillUsageStats(
        call_count=3,
        success_count=0,
        failure_count=3,
        last_used_at=datetime.now(UTC),
    )
    skill = create_skill_metadata("new_skill", usage_stats=stats)
    reason = strategy.should_forget(skill)

    # Should not be forgotten due to quality (not enough calls)
    if reason:
        assert reason.reason_type != "low_quality"


def test_low_quality_needs_observed_outcomes_not_just_uses() -> None:
    """Uses without an observed outcome carry no quality evidence, however many there are."""
    config = CuratorConfig(min_call_count_for_quality_check=5, min_success_rate=0.5)
    strategy = DefaultForgettingStrategy(config)

    never_observed = SkillUsageStats(call_count=50, last_used_at=datetime.now(UTC))
    few_observed = SkillUsageStats(call_count=50, failure_count=3, last_used_at=datetime.now(UTC))

    for stats in (never_observed, few_observed):
        reason = strategy.should_forget(create_skill_metadata("busy_skill", usage_stats=stats))
        assert reason is None


def test_doctor_ignores_heavily_used_skill_without_observed_outcomes() -> None:
    cfg = CuratorConfig(min_call_count_for_quality_check=5, min_success_rate=0.3)
    stats = SkillUsageStats(call_count=40, last_used_at=datetime.now(UTC))

    diagnosis = evaluate_skill_health_findings([create_skill_metadata("advisory_skill", usage_stats=stats)], cfg)

    assert diagnosis.findings == []


def test_select_lru_candidates() -> None:
    """Test LRU candidate selection."""
    config = CuratorConfig(max_skills=3)
    strategy = DefaultForgettingStrategy(config)

    # Create skills with different last_used_at
    skills = [
        create_skill_metadata(
            f"skill_{i}",
            usage_stats=SkillUsageStats(
                call_count=1,
                success_count=1,
                failure_count=0,
                last_used_at=datetime.now(UTC) - timedelta(days=i),
            ),
        )
        for i in range(5)
    ]

    candidates = strategy.select_lru_candidates(skills)

    # Should select 2 LRU skills (5 total - 3 max = 2 to remove)
    assert len(candidates) == 2
    assert all(c.reason_type == "lru_eviction" for c in candidates)


def test_select_lru_candidates_no_eviction_needed() -> None:
    """Test that LRU doesn't evict when under limit."""
    config = CuratorConfig(max_skills=10)
    strategy = DefaultForgettingStrategy(config)

    skills = [
        create_skill_metadata(
            f"skill_{i}",
            usage_stats=SkillUsageStats(
                call_count=1,
                success_count=1,
                failure_count=0,
                last_used_at=datetime.now(UTC),
            ),
        )
        for i in range(5)
    ]

    candidates = strategy.select_lru_candidates(skills)

    # Should not evict any (5 < 10)
    assert len(candidates) == 0


def test_curator_config_round_trip() -> None:
    """CuratorConfig to_dict / from_dict preserves consolidation default false."""
    config = CuratorConfig(stale_after_days=14, consolidation_enabled=False)
    data = config.to_dict()
    assert data["stale_after_days"] == 14
    assert data["consolidation_enabled"] is False

    restored = CuratorConfig.from_dict(data)
    assert restored.stale_after_days == 14
    assert restored.consolidation_enabled is False

    defaults = CuratorConfig.from_dict(None)
    assert defaults.consolidation_enabled is False


def test_should_not_forget_pinned_or_evolution_locked() -> None:
    config = CuratorConfig(stale_after_days=7, grace_period_days=0)
    strategy = DefaultForgettingStrategy(config)
    old = datetime.now(UTC) - timedelta(days=100)
    stats = SkillUsageStats(call_count=0, success_count=0, failure_count=0, created_at=old, pinned=True)
    pinned = create_skill_metadata("pinned_skill", usage_stats=stats)
    assert strategy.should_forget(pinned) is None

    unlocked_stats = SkillUsageStats(call_count=0, success_count=0, failure_count=0, created_at=old)
    locked = SkillMetadata(
        name="locked_skill",
        description="Evolution locked",
        usage_stats=unlocked_stats,
        evolution_locked=True,
    )
    assert strategy.should_forget(locked) is None


def test_grace_period_exempt() -> None:
    config = CuratorConfig(stale_after_days=7, grace_period_days=30)
    strategy = DefaultForgettingStrategy(config)
    recent = datetime.now(UTC) - timedelta(days=5)
    stats = SkillUsageStats(call_count=0, success_count=0, failure_count=0, created_at=recent)
    skill = create_skill_metadata("grace_skill", usage_stats=stats)
    assert strategy.should_forget(skill) is None


def test_archived_skill_skipped() -> None:
    config = CuratorConfig(stale_after_days=7, grace_period_days=0)
    strategy = DefaultForgettingStrategy(config)
    old = datetime.now(UTC) - timedelta(days=200)
    stats = SkillUsageStats(
        call_count=1,
        success_count=1,
        failure_count=0,
        created_at=old,
        last_used_at=old,
        lifecycle_status=SkillLifecycleStatus.ARCHIVED,
    )
    skill = create_skill_metadata("archived_skill", usage_stats=stats)
    assert strategy.should_forget(skill) is None


def test_stale_skill_promoted_to_archive() -> None:
    config = CuratorConfig(stale_after_days=30, archive_after_days=60, grace_period_days=0)
    strategy = DefaultForgettingStrategy(config)
    stale_since = datetime.now(UTC) - timedelta(days=90)
    stats = SkillUsageStats(
        call_count=5,
        success_count=5,
        failure_count=0,
        created_at=stale_since,
        last_used_at=stale_since,
        lifecycle_status=SkillLifecycleStatus.STALE,
    )
    skill = create_skill_metadata("stale_to_archive", usage_stats=stats)
    reason = strategy.should_forget(skill)
    assert reason is not None
    assert reason.reason_type == "archive"
    assert reason.target_status == SkillLifecycleStatus.ARCHIVED


def test_strategy_config_property() -> None:
    config = CuratorConfig(max_skills=5)
    strategy = DefaultForgettingStrategy(config)
    assert strategy.config.max_skills == 5


def test_forgetting_reason_dataclass() -> None:
    """Test ForgettingReason dataclass."""
    stats = SkillUsageStats(call_count=1, success_count=0, failure_count=1)
    reason = ForgettingReason(
        skill_name="test_skill",
        reason_type="stale",
        reason_message="Never used for 37+ days",
        stats=stats,
    )

    assert reason.skill_name == "test_skill"
    assert reason.reason_type == "stale"
    assert reason.reason_message == "Never used for 37+ days"
    assert reason.stats.call_count == 1


def test_evaluate_skill_health_findings_wrong_but_frequent() -> None:
    """Test detecting wrong_but_frequent finding (Hermes Failure Mode #142)."""
    cfg = CuratorConfig(min_call_count_for_quality_check=5, min_success_rate=0.3)
    bad_stats = SkillUsageStats(
        call_count=20,
        success_count=2,  # 10% success rate
        failure_count=18,
        pinned=True,  # Pinned exempts it from LRU eviction!
        lifecycle_status=SkillLifecycleStatus.ACTIVE,
    )
    bad_skill = create_skill_metadata("buggy_crawler", usage_stats=bad_stats)

    good_stats = SkillUsageStats(
        call_count=10,
        success_count=9,
        failure_count=1,
        pinned=False,
        lifecycle_status=SkillLifecycleStatus.ACTIVE,
    )
    good_skill = create_skill_metadata("good_helper", usage_stats=good_stats)

    diagnosis = evaluate_skill_health_findings([bad_skill, good_skill], cfg)

    assert diagnosis.total_skills == 2
    assert diagnosis.active_skills == 2
    assert diagnosis.pinned_skills == 1
    assert len(diagnosis.findings) == 1

    f = diagnosis.findings[0]
    assert f.skill_name == "buggy_crawler"
    assert f.finding_type == "wrong_but_frequent"
    assert f.severity == "critical"
    assert f.pinned is True
    assert f.recommended_action == "unpin_and_archive"
    # The UI phrases the finding from these parameters; the English `message` is never shown.
    assert f.details == {"observed_count": 20}
    assert diagnosis.health_score < 100.0


def test_evaluate_skill_health_findings_stale_pinned() -> None:
    """A pinned skill idle past the stale threshold is reported with its idle day count; a recent one is not."""
    cfg = CuratorConfig(stale_after_days=30)
    now = datetime.now(UTC)

    def pinned_skill(name: str, idle_days: int) -> SkillMetadata:
        return create_skill_metadata(
            name,
            usage_stats=SkillUsageStats(
                call_count=3,
                success_count=3,
                failure_count=0,
                pinned=True,
                last_used_at=now - timedelta(days=idle_days),
                lifecycle_status=SkillLifecycleStatus.ACTIVE,
            ),
        )

    diagnosis = evaluate_skill_health_findings(
        [pinned_skill("forgotten_notes", 45), pinned_skill("fresh_notes", 10)], cfg
    )

    assert len(diagnosis.findings) == 1
    f = diagnosis.findings[0]
    assert f.skill_name == "forgotten_notes"
    assert f.finding_type == "stale_pinned"
    assert f.severity == "info"
    assert f.pinned is True
    assert f.recommended_action == "unpin_and_archive"
    assert f.details == {"days_inactive": 45}


def test_evaluate_skill_health_findings_bloat() -> None:
    """Test detecting library bloat when active skills exceed max_skills."""
    cfg = CuratorConfig(max_skills=2)
    skills = [
        create_skill_metadata(
            f"skill_{i}",
            usage_stats=SkillUsageStats(
                call_count=1,
                success_count=1,
                failure_count=0,
                lifecycle_status=SkillLifecycleStatus.ACTIVE,
            ),
        )
        for i in range(5)
    ]

    diagnosis = evaluate_skill_health_findings(skills, cfg)
    assert diagnosis.total_skills == 5
    assert diagnosis.active_skills == 5
    bloat = [f for f in diagnosis.findings if f.finding_type == "hoarding_bloat"]
    assert len(bloat) == 1
    assert bloat[0].severity == "warning"
    assert bloat[0].details == {"active_count": 5, "max_skills": 2, "excess": 3}
