"""Unit tests for Harness SkillHealthEvaluator and digest types."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from myrm_agent_harness.observability.digest.health_evaluator import (
    SkillHealthEvaluator,
)
from myrm_agent_harness.observability.digest.types import (
    SkillCompoundingMetrics,
    SkillHealthStatus,
)


def test_dormant_skill_zero_invocations():
    """Skill with 0 invocations should be classified as STALE with 0 score."""
    metrics = SkillCompoundingMetrics(
        skill_id="legacy-script",
        invocations=0,
        successful_invocations=0,
        adopted_outputs=0,
        retry_count=0,
        distinct_sessions=0,
        last_invoked_at=None,
    )
    score = SkillHealthEvaluator.evaluate(metrics)
    assert score.skill_id == "legacy-script"
    assert score.health_score == 0.0
    assert score.status == SkillHealthStatus.STALE
    assert score.adoption_rate == 0.0
    assert score.success_rate == 0.0
    assert "not been invoked" in score.actionable_recommendation


def test_stale_skill_inactive_over_threshold():
    """Skill inactive for > 30 days should be classified as STALE with 15.0 score."""
    now = datetime.now(UTC)
    old_time = now - timedelta(days=45)
    metrics = SkillCompoundingMetrics(
        skill_id="old-ocr",
        invocations=10,
        successful_invocations=8,
        adopted_outputs=8,
        retry_count=1,
        distinct_sessions=4,
        last_invoked_at=old_time,
    )
    score = SkillHealthEvaluator.evaluate(
        metrics, reference_time=now, stale_days_threshold=30
    )
    assert score.health_score == 15.0
    assert score.status == SkillHealthStatus.STALE
    assert "Inactive for 45 days" in score.actionable_recommendation


def test_star_skill_high_adoption_and_success():
    """Skill with high volume, high success, and high adoption should be STAR."""
    now = datetime.now(UTC)
    metrics = SkillCompoundingMetrics(
        skill_id="code-reviewer",
        invocations=25,
        successful_invocations=25,
        adopted_outputs=24,
        retry_count=0,
        distinct_sessions=10,
        last_invoked_at=now,
    )
    score = SkillHealthEvaluator.evaluate(metrics, reference_time=now)
    assert score.status == SkillHealthStatus.STAR
    assert score.health_score >= 80.0
    assert "Star compounding asset" in score.actionable_recommendation


def test_at_risk_skill_low_success_rate():
    """Skill with low success rate (< 0.65) should be marked AT_RISK."""
    now = datetime.now(UTC)
    metrics = SkillCompoundingMetrics(
        skill_id="flaky-api",
        invocations=20,
        successful_invocations=10,  # 50% success
        adopted_outputs=8,
        retry_count=8,
        distinct_sessions=5,
        last_invoked_at=now,
    )
    score = SkillHealthEvaluator.evaluate(metrics, reference_time=now)
    assert score.status == SkillHealthStatus.AT_RISK
    assert "At-risk asset" in score.actionable_recommendation


def test_healthy_skill_standard_rotation():
    """Skill with moderate success rate and active rotation should be HEALTHY."""
    now = datetime.now(UTC)
    metrics = SkillCompoundingMetrics(
        skill_id="daily-digest",
        invocations=10,
        successful_invocations=8,
        adopted_outputs=7,
        retry_count=1,
        distinct_sessions=3,
        last_invoked_at=now,
    )
    score = SkillHealthEvaluator.evaluate(metrics, reference_time=now)
    assert score.status == SkillHealthStatus.HEALTHY
    assert "Healthy asset in active rotation" in score.actionable_recommendation
