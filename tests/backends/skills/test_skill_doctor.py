"""Tests for the skill library doctor."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from myrm_agent_harness.backends.skills.curator_config import CuratorConfig
from myrm_agent_harness.backends.skills.skill_doctor import evaluate_skill_health_findings
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


def test_doctor_ignores_heavily_used_skill_without_observed_outcomes() -> None:
    cfg = CuratorConfig(min_call_count_for_quality_check=5, min_success_rate=0.3)
    stats = SkillUsageStats(call_count=40, last_used_at=datetime.now(UTC))

    diagnosis = evaluate_skill_health_findings([create_skill_metadata("advisory_skill", usage_stats=stats)], cfg)

    assert diagnosis.findings == []


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
