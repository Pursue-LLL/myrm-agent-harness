"""Tests for skill_analyze meta-tool."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from myrm_agent_harness.agent.meta_tools.skills.analyze.skill_analyze_tool import (
    _format_candidate_list,
    _format_detailed_suggestions,
    create_skill_analyze_tool,
)
from myrm_agent_harness.backends.skills.forgetting_strategy import ForgettingConfig, ForgettingReason
from myrm_agent_harness.backends.skills.types import SkillMetadata, SkillUsageStats


def create_test_skill(
    name: str,
    call_count: int = 0,
    success_count: int = 0,
    failure_count: int = 0,
    last_used_at: datetime | None = None,
    *,
    created_at: datetime | None = None,
) -> SkillMetadata:
    """Helper to create test skill metadata."""
    stats = SkillUsageStats(
        call_count=call_count,
        success_count=success_count,
        failure_count=failure_count,
        last_used_at=last_used_at,
        total_duration_ms=float(call_count * 100),
        created_at=created_at or datetime.now(UTC),
    )
    skill = SkillMetadata(name=name, description=f"Test skill {name}")
    object.__setattr__(skill, "usage_stats", stats)
    return skill


def test_skill_analyze_no_skills() -> None:
    """Test skill_analyze with no skills loaded."""
    tool = create_skill_analyze_tool(get_all_skills_fn=lambda: [])
    result = tool.invoke({"action": "list_low_quality"})
    assert "No skills loaded" in result


def test_skill_analyze_all_healthy() -> None:
    """Test skill_analyze when all skills are healthy."""
    healthy_skill = create_test_skill(
        "healthy_skill", call_count=10, success_count=9, failure_count=1, last_used_at=datetime.now(UTC)
    )

    tool = create_skill_analyze_tool(get_all_skills_fn=lambda: [healthy_skill])
    result = tool.invoke({"action": "list_low_quality"})

    assert "All 1 skills are healthy" in result
    assert "No cleanup needed" in result


def test_skill_analyze_list_low_quality_stale() -> None:
    """Test list_low_quality action with stale skills."""
    old_created = datetime.now(UTC) - timedelta(days=60)
    stale_skill = create_test_skill(
        "stale_skill",
        call_count=0,
        success_count=0,
        failure_count=0,
        last_used_at=None,
        created_at=old_created,
    )

    config = ForgettingConfig(stale_after_days=30, grace_period_days=0)
    tool = create_skill_analyze_tool(get_all_skills_fn=lambda: [stale_skill], forgetting_config=config)
    result = tool.invoke({"action": "list_low_quality"})

    assert "1 skills that may need cleanup" in result
    assert "stale_skill" in result
    assert "stale" in result.lower()


def test_skill_analyze_list_low_quality_multiple() -> None:
    """Test list_low_quality with multiple candidate types."""
    old_created = datetime.now(UTC) - timedelta(days=60)
    stale_skill = create_test_skill("stale", call_count=0, last_used_at=None, created_at=old_created)
    low_quality_skill = create_test_skill(
        "low_quality", call_count=10, success_count=2, failure_count=8, last_used_at=datetime.now(UTC)
    )
    inactive_skill = create_test_skill(
        "inactive",
        call_count=5,
        success_count=4,
        failure_count=1,
        last_used_at=datetime.now(UTC) - timedelta(days=60),
        created_at=datetime.now(UTC) - timedelta(days=90),
    )

    config = ForgettingConfig(
        stale_after_days=30,
        grace_period_days=0,
        min_call_count_for_quality_check=5,
        min_success_rate=0.5,
    )
    tool = create_skill_analyze_tool(
        get_all_skills_fn=lambda: [stale_skill, low_quality_skill, inactive_skill], forgetting_config=config
    )
    result = tool.invoke({"action": "list_low_quality"})

    assert "3 skills that may need cleanup" in result
    assert "stale" in result
    assert "low_quality" in result
    assert "inactive" in result


def test_skill_analyze_suggest_cleanup() -> None:
    """Test suggest_cleanup action with detailed output."""
    old_created = datetime.now(UTC) - timedelta(days=60)
    stale_skill = create_test_skill("stale_skill", call_count=0, last_used_at=None, created_at=old_created)
    low_quality_skill = create_test_skill(
        "low_quality_skill", call_count=10, success_count=2, failure_count=8, last_used_at=datetime.now(UTC)
    )

    config = ForgettingConfig(
        stale_after_days=30,
        grace_period_days=0,
        min_call_count_for_quality_check=5,
        min_success_rate=0.5,
    )
    tool = create_skill_analyze_tool(
        get_all_skills_fn=lambda: [stale_skill, low_quality_skill], forgetting_config=config
    )
    result = tool.invoke({"action": "suggest_cleanup"})

    assert "cleanup suggestions" in result.lower()
    assert "2/2 skills" in result
    assert "stale_skill" in result
    assert "low_quality_skill" in result
    assert "STALE" in result
    assert "LOW QUALITY" in result
    assert "Recommendation" in result
    assert "IMPORTANT" in result


def test_skill_analyze_lru_eviction() -> None:
    """Test LRU eviction candidates."""
    # Create 6 skills where 5 is the max
    skills = []
    for i in range(6):
        skill = create_test_skill(
            f"skill_{i}",
            call_count=5,
            success_count=5,
            failure_count=0,
            last_used_at=datetime.now(UTC) - timedelta(days=i),
            created_at=datetime.now(UTC) - timedelta(days=90),
        )
        skills.append(skill)

    config = ForgettingConfig(max_skills=5, stale_after_days=9999, grace_period_days=0)
    tool = create_skill_analyze_tool(get_all_skills_fn=lambda: skills, forgetting_config=config)
    result = tool.invoke({"action": "list_low_quality"})

    assert "1 skills that may need cleanup" in result
    assert "lru" in result.lower()
    # Oldest skill (skill_5) should be LRU candidate
    assert "skill_5" in result


def test_format_candidate_list() -> None:
    """Test _format_candidate_list output formatting."""
    stats = SkillUsageStats(
        call_count=10, success_count=2, failure_count=8, last_used_at=datetime.now(UTC), total_duration_ms=1000.0
    )
    reason = ForgettingReason(
        skill_name="test_skill", reason_type="low_quality", reason_message="Test reason", stats=stats
    )

    result = _format_candidate_list([reason])

    assert "1 skills that may need cleanup" in result
    assert "test_skill" in result
    assert "low_quality" in result
    assert "Calls: 10" in result
    assert "Success rate: 20" in result  # 2/10 = 20%
    assert "Test reason" in result


def test_format_detailed_suggestions() -> None:
    """Test _format_detailed_suggestions output formatting."""
    stats1 = SkillUsageStats(call_count=0, success_count=0, failure_count=0, last_used_at=None, total_duration_ms=0.0)
    reason1 = ForgettingReason(skill_name="stale_skill", reason_type="stale", reason_message="Never used", stats=stats1)

    stats2 = SkillUsageStats(
        call_count=10, success_count=2, failure_count=8, last_used_at=datetime.now(UTC), total_duration_ms=1000.0
    )
    reason2 = ForgettingReason(
        skill_name="low_quality_skill", reason_type="low_quality", reason_message="Low success", stats=stats2
    )

    all_skills = [create_test_skill("skill1"), create_test_skill("skill2")]

    result = _format_detailed_suggestions([reason1, reason2], all_skills)

    assert "2/2 skills" in result
    assert "STALE" in result
    assert "LOW QUALITY" in result
    assert "stale_skill" in result
    assert "low_quality_skill" in result
    assert "Recommendation" in result
    assert "IMPORTANT" in result
