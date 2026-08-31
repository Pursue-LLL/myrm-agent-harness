"""Unit tests for Team Weekly Digest, Skill Health Evaluator, and Markdown Renderer."""

from datetime import datetime, timezone

import pytest

from myrm_agent_harness.observability.digest import (
    MemberActivitySummary,
    SkillCompoundingMetrics,
    SkillHealthEvaluator,
    SkillHealthScore,
    SkillHealthStatus,
    TeamDigestRenderer,
    TeamWeeklyDigest,
)


def test_skill_health_evaluator_star_and_at_risk():
    """Test multi-dimensional skill compounding evaluation and status classifications."""
    # 1. High adoption Star skill
    star_metrics = SkillCompoundingMetrics(
        skill_id="database_migration_guard",
        invocations=30,
        successful_invocations=30,
        adopted_outputs=28,
        retry_count=0,
        distinct_sessions=25,
        last_invoked_at=datetime.now(timezone.utc),
    )
    star_score = SkillHealthEvaluator.evaluate(star_metrics)
    assert star_score.status == SkillHealthStatus.STAR
    assert star_score.health_score >= 80.0
    assert star_score.success_rate == 1.0
    assert "Star compounding asset" in star_score.actionable_recommendation

    # 2. Fragile / At-Risk skill with high failure rate
    at_risk_metrics = SkillCompoundingMetrics(
        skill_id="legacy_scraper",
        invocations=20,
        successful_invocations=10,  # 50% success
        adopted_outputs=8,
        retry_count=12,
        distinct_sessions=5,
        last_invoked_at=datetime.now(timezone.utc),
    )
    at_risk_score = SkillHealthEvaluator.evaluate(at_risk_metrics)
    assert at_risk_score.status == SkillHealthStatus.AT_RISK
    assert at_risk_score.success_rate == 0.5
    assert "At-risk asset" in at_risk_score.actionable_recommendation

    # 3. Dormant / Stale skill
    stale_metrics = SkillCompoundingMetrics(
        skill_id="old_tool",
        invocations=0,
    )
    stale_score = SkillHealthEvaluator.evaluate(stale_metrics)
    assert stale_score.status == SkillHealthStatus.STALE
    assert stale_score.health_score == 0.0


def test_team_digest_renderer_markdown_output():
    """Test generating structured Markdown newsletter from TeamWeeklyDigest."""
    star_skill = SkillHealthScore(
        skill_id="fastapi_generator",
        health_score=94.5,
        status=SkillHealthStatus.STAR,
        adoption_rate=0.92,
        success_rate=1.0,
        reuse_breadth=0.85,
        actionable_recommendation="🌟 Star asset",
    )

    member = MemberActivitySummary(
        user_id="alice",
        total_sessions=14,
        total_steps=85,
        tokens_consumed=150_000,
        skills_created_or_refined=3,
        estimated_hours_saved=12.5,
    )

    digest = TeamWeeklyDigest(
        period_start=datetime(2026, 8, 24, tzinfo=timezone.utc),
        period_end=datetime(2026, 8, 30, tzinfo=timezone.utc),
        team_name="Vortex AI Squad",
        total_active_members=5,
        total_sessions=42,
        total_tokens_consumed=850_000,
        estimated_total_hours_saved=38.0,
        star_skills=[star_skill],
        member_rankings=[member],
        top_friction_modules=["sandbox_network_timeout", "large_json_serialization"],
    )

    md = TeamDigestRenderer.render_markdown(digest)
    assert "# 📊 Vortex AI Squad · AI Agent 协作周报" in md
    assert "预估节省研发工时" in md
    assert "38.0" in md
    assert "`fastapi_generator`" in md
    assert "`alice`" in md
    assert "sandbox_network_timeout" in md
