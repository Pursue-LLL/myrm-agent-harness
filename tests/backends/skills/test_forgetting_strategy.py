"""Tests for SkillForgettingStrategy."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from myrm_agent_harness.backends.skills.forgetting_strategy import (
    DefaultForgettingStrategy,
    ForgettingConfig,
    ForgettingReason,
)
from myrm_agent_harness.backends.skills.types import SkillMetadata, SkillUsageStats


def create_skill_metadata(name: str, usage_stats: SkillUsageStats | None = None) -> SkillMetadata:
    """Helper to create SkillMetadata for testing."""
    skill = SkillMetadata(name=name, description="Test skill")
    if usage_stats:
        object.__setattr__(skill, "usage_stats", usage_stats)
    return skill


def test_should_forget_stale_skill() -> None:
    """Test that stale skills are marked for forgetting."""
    config = ForgettingConfig(stale_after_days=30)
    strategy = DefaultForgettingStrategy(config)

    # Skill never used (default last_used_at is None)
    skill = create_skill_metadata("stale_skill")
    reason = strategy.should_forget(skill)

    assert reason is not None
    assert reason.reason_type == "stale"


def test_should_forget_low_quality_skill() -> None:
    """Test that low quality skills are marked for forgetting."""
    config = ForgettingConfig(min_call_count_for_quality_check=5, min_success_rate=0.5)
    strategy = DefaultForgettingStrategy(config)

    # Skill with low success rate
    stats = SkillUsageStats(
        call_count=10, success_count=2, failure_count=8, last_used_at=datetime.now(UTC), total_duration_ms=1000.0
    )
    skill = create_skill_metadata("low_quality_skill", usage_stats=stats)
    reason = strategy.should_forget(skill)

    assert reason is not None
    assert reason.reason_type == "low_quality"
    assert ("20" in reason.reason_message or "0.2" in reason.reason_message) and "%" in reason.reason_message


def test_should_not_forget_high_quality_skill() -> None:
    """Test that high quality skills are not forgotten."""
    config = ForgettingConfig(stale_after_days=30)
    strategy = DefaultForgettingStrategy(config)

    # Skill with high success rate and recent usage
    stats = SkillUsageStats(
        call_count=10, success_count=9, failure_count=1, last_used_at=datetime.now(UTC), total_duration_ms=1000.0
    )
    skill = create_skill_metadata("good_skill", usage_stats=stats)
    reason = strategy.should_forget(skill)

    assert reason is None


def test_should_forget_inactive_skill() -> None:
    """Test that inactive skills are marked for forgetting."""
    config = ForgettingConfig(stale_after_days=30)
    strategy = DefaultForgettingStrategy(config)

    # Skill used long ago
    old_date = datetime.now(UTC) - timedelta(days=60)
    stats = SkillUsageStats(
        call_count=10, success_count=8, failure_count=2, last_used_at=old_date, total_duration_ms=1000.0
    )
    skill = create_skill_metadata("inactive_skill", usage_stats=stats)
    reason = strategy.should_forget(skill)

    assert reason is not None
    assert reason.reason_type == "inactive"
    assert "60" in reason.reason_message or "inactive" in reason.reason_message.lower()


def test_low_quality_threshold_not_met() -> None:
    """Test that skills with few calls are not judged by quality."""
    config = ForgettingConfig(min_call_count_for_quality_check=10, min_success_rate=0.5)
    strategy = DefaultForgettingStrategy(config)

    # Skill with low success rate but few calls
    stats = SkillUsageStats(
        call_count=3, success_count=0, failure_count=3, last_used_at=datetime.now(UTC), total_duration_ms=300.0
    )
    skill = create_skill_metadata("new_skill", usage_stats=stats)
    reason = strategy.should_forget(skill)

    # Should not be forgotten due to quality (not enough calls)
    if reason:
        assert reason.reason_type != "low_quality"


def test_select_lru_candidates() -> None:
    """Test LRU candidate selection."""
    config = ForgettingConfig(max_skills=3)
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
                total_duration_ms=100.0,
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
    config = ForgettingConfig(max_skills=10)
    strategy = DefaultForgettingStrategy(config)

    skills = [
        create_skill_metadata(
            f"skill_{i}",
            usage_stats=SkillUsageStats(
                call_count=1, success_count=1, failure_count=0, last_used_at=datetime.now(UTC), total_duration_ms=100.0
            ),
        )
        for i in range(5)
    ]

    candidates = strategy.select_lru_candidates(skills)

    # Should not evict any (5 < 10)
    assert len(candidates) == 0


def test_forgetting_reason_dataclass() -> None:
    """Test ForgettingReason dataclass."""
    stats = SkillUsageStats(call_count=1, success_count=0, failure_count=1)
    reason = ForgettingReason(
        skill_name="test_skill", reason_type="stale", reason_message="Never used for 37+ days", stats=stats
    )

    assert reason.skill_name == "test_skill"
    assert reason.reason_type == "stale"
    assert reason.reason_message == "Never used for 37+ days"
    assert reason.stats.call_count == 1
