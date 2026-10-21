"""Unit tests for Custom Agent Insights and Operational Observability in myrm_agent_harness.observability.agent_insights."""

from concurrent.futures import ThreadPoolExecutor

from myrm_agent_harness.observability.agent_insights import (
    CustomAgentInsightsSnapshot,
    CustomAgentInsightsTracker,
    SkillExecutionStatus,
)


def test_initial_insights_snapshot() -> None:
    """Verify that an unrecorded agent returns a clean empty snapshot."""
    tracker = CustomAgentInsightsTracker()
    snapshot: CustomAgentInsightsSnapshot = tracker.get_insights_snapshot(agent_id="agent_unknown")

    assert snapshot.agent_id == "agent_unknown"
    assert snapshot.time_window_days == 7
    assert snapshot.total_interactions == 0
    assert snapshot.total_tokens_consumed == 0
    assert len(snapshot.intent_clusters) == 0
    assert len(snapshot.skill_funnel) == 0
    assert snapshot.hitl_metrics.total_tasks == 0
    assert snapshot.hitl_metrics.hitl_interception_rate_pct == 0.0


def test_intent_clustering_and_shares() -> None:
    """Verify that interactions are clustered and top categories sorted by volume."""
    tracker = CustomAgentInsightsTracker()
    aid = "dev_assistant"

    tracker.record_interaction(aid, "code_refactor", "Refactor payment service", tokens=1200)
    tracker.record_interaction(aid, "code_refactor", "Clean up database queries", tokens=800)
    tracker.record_interaction(aid, "code_refactor", "Extract helper utility", tokens=500)
    tracker.record_interaction(aid, "bug_investigation", "Fix null pointer in auth", tokens=1500)
    tracker.record_interaction(aid, "bug_investigation", "Trace 500 error in checkout", tokens=1100)
    tracker.record_interaction(aid, "test_generation", "Write unit test for order", tokens=900)

    snapshot = tracker.get_insights_snapshot(aid, window_days=7)
    assert snapshot.total_interactions == 6
    assert snapshot.total_tokens_consumed == 6000
    assert len(snapshot.intent_clusters) == 3

    # Most frequent cluster should be code_refactor (3/6 = 50.0%)
    c1 = snapshot.intent_clusters[0]
    assert c1.intent_category == "code_refactor"
    assert c1.request_count == 3
    assert c1.share_pct == 50.0

    # Second cluster bug_investigation (2/6 = 33.3%)
    c2 = snapshot.intent_clusters[1]
    assert c2.intent_category == "bug_investigation"
    assert c2.request_count == 2
    assert c2.share_pct == 33.3


def test_skill_health_funnel_and_latency() -> None:
    """Verify skill funnel metrics including call counts, success rate, and P95 latency."""
    tracker = CustomAgentInsightsTracker()
    aid = "research_agent"

    # web_search skill: 4 calls (3 success, 1 failure)
    tracker.record_skill_execution(aid, "web_search", 150.0, SkillExecutionStatus.SUCCESS)
    tracker.record_skill_execution(aid, "web_search", 200.0, SkillExecutionStatus.SUCCESS)
    tracker.record_skill_execution(aid, "web_search", 250.0, SkillExecutionStatus.SUCCESS)
    tracker.record_skill_execution(
        aid, "web_search", 500.0, SkillExecutionStatus.FAILURE, error_reason="HTTP 429 Rate Limit"
    )

    # file_reader skill: 2 calls (all success)
    tracker.record_skill_execution(aid, "file_reader", 20.0, SkillExecutionStatus.SUCCESS)
    tracker.record_skill_execution(aid, "file_reader", 30.0, SkillExecutionStatus.SUCCESS)

    snapshot = tracker.get_insights_snapshot(aid)
    assert len(snapshot.skill_funnel) == 2

    ws = snapshot.skill_funnel[0]
    assert ws.skill_name == "web_search"
    assert ws.total_calls == 4
    assert ws.success_rate_pct == 75.0
    assert ws.avg_latency_ms == 275.0
    assert "HTTP 429 Rate Limit" in ws.top_error_reasons

    fr = snapshot.skill_funnel[1]
    assert fr.skill_name == "file_reader"
    assert fr.total_calls == 2
    assert fr.success_rate_pct == 100.0
    assert fr.avg_latency_ms == 25.0


def test_hitl_friction_and_token_roi() -> None:
    """Verify HITL bottleneck calculations and artifact deliverable Token ROI."""
    tracker = CustomAgentInsightsTracker()
    aid = "finance_analyst"

    # 4 tasks: 2 intercepted (waited 15s and 25s), 2 automated; generated 8 deliverables using 20k tokens
    tracker.record_hitl_task(aid, intercepted=True, wait_seconds=15.0, deliverables_count=2, tokens_consumed=5000)
    tracker.record_hitl_task(aid, intercepted=True, wait_seconds=25.0, deliverables_count=2, tokens_consumed=5000)
    tracker.record_hitl_task(aid, intercepted=False, wait_seconds=0.0, deliverables_count=2, tokens_consumed=5000)
    tracker.record_hitl_task(aid, intercepted=False, wait_seconds=0.0, deliverables_count=2, tokens_consumed=5000)

    snapshot = tracker.get_insights_snapshot(aid)
    hitl = snapshot.hitl_metrics
    assert hitl.total_tasks == 4
    assert hitl.hitl_intercepted_tasks == 2
    assert hitl.hitl_interception_rate_pct == 50.0
    assert hitl.avg_approval_wait_seconds == 20.0
    # 8 deliverables / 2.0 (20k tokens) = 4.0
    assert hitl.token_roi_ratio == 4.0


def test_reset_and_concurrent_safety() -> None:
    """Verify data isolation across resets and concurrent recording."""
    tracker = CustomAgentInsightsTracker()
    aid = "concurrent_agent"

    def worker_task(i: int) -> None:
        tracker.record_interaction(aid, f"intent_{i % 3}", f"query {i}", tokens=100)
        tracker.record_skill_execution(aid, "bash", 50.0)
        tracker.record_hitl_task(aid, intercepted=(i % 2 == 0), wait_seconds=5.0)

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(worker_task, range(60)))

    snap1 = tracker.get_insights_snapshot(aid)
    assert snap1.total_interactions == 60
    assert snap1.hitl_metrics.total_tasks == 60

    tracker.reset(agent_id=aid)
    snap2 = tracker.get_insights_snapshot(aid)
    assert snap2.total_interactions == 0
    assert snap2.hitl_metrics.total_tasks == 0
