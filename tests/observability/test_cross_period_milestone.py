"""
[INPUT]: CrossPeriodMilestoneEngine tracking routines and mock activity events.
[OUTPUT]: Pytest suite validating cross-period comparative reports, XP progression, daily quests, and badges.
[POS]: myrm-agent-harness/tests/observability/test_cross_period_milestone.py
"""

import pytest
from myrm_agent_harness.observability.cross_period_milestone import (
    AgentActivityEvent,
    CrossPeriodMilestoneEngine,
    PeriodType,
)


@pytest.fixture
def engine() -> CrossPeriodMilestoneEngine:
    eng = CrossPeriodMilestoneEngine()
    eng.reset()
    return eng


def test_activity_recording_and_xp_progression(engine: CrossPeriodMilestoneEngine) -> None:
    # 1. User records code review activity
    res = engine.record_activity(
        AgentActivityEvent(
            user_id="user_alice",
            user_name="Alice",
            agent_id="coding_agent",
            agent_name="Coding Specialist",
            tokens_in=4000,
            tokens_out=2000,
            cost_usd=0.035,
            latency_ms=1200.0,
            success=True,
            task_category="code_review",
            timestamp_iso="2026-10-12T08:00:00Z",
        )
    )

    assert res["status"] == "recorded"
    profile = engine.get_user_gamified_profile("user_alice")
    assert profile.user_name == "Alice"
    assert profile.total_xp > 0

    # Task for code review should be completed and awarded bonus XP
    task = next((t for t in profile.daily_tasks if t.id == "task_code_review"), None)
    assert task is not None
    assert task.is_completed is True
    assert task.progress == 1

    # First collab badge unlocked
    badge_first = next((b for b in profile.badges if b.id == "badge_first_collab"), None)
    assert badge_first is not None
    assert badge_first.is_unlocked is True


def test_cross_period_pivot_report_growth_calculation(engine: CrossPeriodMilestoneEngine) -> None:
    # Add events in previous pseudo-period
    engine.record_activity(
        AgentActivityEvent(
            user_id="user_bob",
            user_name="Bob",
            agent_id="workbuddy",
            agent_name="WorkBuddy Prime",
            tokens_in=1000,
            tokens_out=500,
            cost_usd=0.01,
            latency_ms=800.0,
            success=True,
            task_category="research",
            timestamp_iso="2026-10-01T10:00:00Z",
        )
    )

    # Add events in current pseudo-period with higher consumption
    engine.record_activity(
        AgentActivityEvent(
            user_id="user_bob",
            user_name="Bob",
            agent_id="workbuddy",
            agent_name="WorkBuddy Prime",
            tokens_in=3000,
            tokens_out=1500,
            cost_usd=0.03,
            latency_ms=900.0,
            success=True,
            task_category="research",
            timestamp_iso="2026-10-12T10:00:00Z",
        )
    )
    engine.record_activity(
        AgentActivityEvent(
            user_id="user_alice",
            user_name="Alice",
            agent_id="hermes",
            agent_name="Hermes Orchestrator",
            tokens_in=5000,
            tokens_out=2500,
            cost_usd=0.05,
            latency_ms=1100.0,
            success=True,
            task_category="multi_agent",
            timestamp_iso="2026-10-12T11:00:00Z",
        )
    )

    report = engine.generate_pivot_report(PeriodType.WEEKLY)
    assert report.current_period.total_tokens > 0
    assert len(report.current_period.agent_breakdowns) >= 1
    # Check token share percentages sum to ~100%
    total_share = sum(b.token_share_pct for b in report.current_period.agent_breakdowns)
    assert 99.0 <= total_share <= 101.0

    # Growth comparison relative to previous period
    assert report.previous_period is not None
    assert report.token_growth_pct is not None
    assert report.token_growth_pct > 0.0


def test_team_adoption_insights_and_claim_task(engine: CrossPeriodMilestoneEngine) -> None:
    engine.record_activity(
        AgentActivityEvent(
            user_id="user_charlie",
            user_name="Charlie",
            agent_id="coding_agent",
            agent_name="Coding Specialist",
            tokens_in=2000,
            tokens_out=1000,
            cost_usd=0.02,
            latency_ms=750.0,
            success=True,
            task_category="code_review",
            timestamp_iso="2026-10-12T12:00:00Z",
        )
    )

    # Claim a daily task manually
    profile = engine.claim_daily_task("user_charlie", "task_research_summary")
    task_res = next((t for t in profile.daily_tasks if t.id == "task_research_summary"), None)
    assert task_res is not None
    assert task_res.is_completed is True

    # Check team adoption insights
    insights = engine.get_team_adoption_insights()
    assert insights.total_active_members >= 1
    assert len(insights.leaderboard) >= 1
    assert insights.leaderboard[0].user_id == "user_charlie"
    assert len(insights.top_task_categories) >= 1
