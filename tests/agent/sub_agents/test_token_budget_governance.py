"""Unit tests for One-Model Multi-Agent Shared Context Token Budget Governance (Item 52)."""

from myrm_agent_harness.agent.sub_agents.token_budget_governance import (
    ConsumptionCategory,
    NudgeSeverity,
    RoleBudgetSpec,
    SharedTokenBudgetGovernor,
)


def test_default_governor_initialization_and_snapshot() -> None:
    gov = SharedTokenBudgetGovernor(
        session_id="sess-gov-01",
        primary_model="claude-3-5-sonnet",
        shared_token_ceiling=50_000,
    )
    snap = gov.get_snapshot()

    assert snap.session_id == "sess-gov-01"
    assert snap.primary_model == "claude-3-5-sonnet"
    assert snap.shared_token_ceiling == 50_000
    assert snap.total_tokens_spent == 0
    assert snap.routing_tokens_spent == 0
    assert snap.execution_tokens_spent == 0
    assert snap.routing_ratio == 0.0
    assert len(snap.active_alerts) == 0


def test_role_budget_registration_and_precheck_passed() -> None:
    gov = SharedTokenBudgetGovernor(session_id="sess-gov-02", shared_token_ceiling=50_000)
    spec = RoleBudgetSpec(
        role_name="architect",
        token_ceiling=15_000,
        stop_condition="halt_and_report",
        allow_overflow=False,
    )
    gov.register_role_budget(spec)

    # Precheck within budget passes
    res = gov.precheck_fanout(role_name="architect", estimated_tokens=4_000)
    assert res.passed is True
    assert res.requested_tokens == 4_000
    assert res.remaining_budget == 50_000


def test_fanout_precheck_role_budget_exceeded() -> None:
    gov = SharedTokenBudgetGovernor(session_id="sess-gov-03", shared_token_ceiling=50_000)
    spec = RoleBudgetSpec(
        role_name="researcher",
        token_ceiling=8_000,
        stop_condition="halt_and_report",
        allow_overflow=False,
    )
    gov.register_role_budget(spec)

    # First turn consumes 6,000 tokens
    gov.record_consumption(
        agent_role="researcher",
        category=ConsumptionCategory.EXECUTION_PAYLOAD,
        prompt_tokens=4_000,
        completion_tokens=2_000,
    )

    # Precheck requesting another 3,000 tokens exceeds 8,000 ceiling
    res = gov.precheck_fanout(role_name="researcher", estimated_tokens=3_000)
    assert res.passed is False
    assert res.remaining_budget == 2_000
    assert "Per-role ceiling exceeded for 'researcher'" in res.reason
    assert "halt_and_report" in res.reason


def test_fanout_precheck_shared_ceiling_exceeded() -> None:
    gov = SharedTokenBudgetGovernor(session_id="sess-gov-04", shared_token_ceiling=10_000)

    # Precheck requesting 12,000 tokens exceeds 10,000 ceiling
    res = gov.precheck_fanout(role_name="general", estimated_tokens=12_000)
    assert res.passed is False
    assert res.remaining_budget == 10_000
    assert "Global shared ceiling exceeded" in res.reason


def test_consumption_recording_and_routing_vs_execution_breakdown() -> None:
    gov = SharedTokenBudgetGovernor(session_id="sess-gov-05", shared_token_ceiling=50_000)

    # 1. Routing overhead turn
    gov.record_consumption(
        agent_role="orchestrator",
        category=ConsumptionCategory.ROUTING_OVERHEAD,
        prompt_tokens=800,
        completion_tokens=200,
        metadata={"step": "intent_dispatch"},
    )

    # 2. Execution payload turn
    gov.record_consumption(
        agent_role="coder",
        category=ConsumptionCategory.EXECUTION_PAYLOAD,
        prompt_tokens=2_000,
        completion_tokens=1_000,
        metadata={"step": "code_gen"},
    )

    snap = gov.get_snapshot()
    assert snap.total_tokens_spent == 4_000
    assert snap.routing_tokens_spent == 1_000
    assert snap.execution_tokens_spent == 3_000
    assert snap.routing_ratio == 0.25  # 1000 / 4000 = 25%
    assert snap.role_usage["orchestrator"] == 1_000
    assert snap.role_usage["coder"] == 3_000


def test_doctor_nudge_alert_high_routing_overhead() -> None:
    gov = SharedTokenBudgetGovernor(session_id="sess-gov-06", shared_token_ceiling=50_000)

    # Spend 1,500 on routing and 1,000 on execution -> total 2,500, ratio 60% > 35%
    gov.record_consumption(
        agent_role="router",
        category=ConsumptionCategory.ROUTING_OVERHEAD,
        prompt_tokens=1_000,
        completion_tokens=500,
    )
    gov.record_consumption(
        agent_role="worker",
        category=ConsumptionCategory.EXECUTION_PAYLOAD,
        prompt_tokens=600,
        completion_tokens=400,
    )

    alerts = gov.evaluate_doctor_nudge(threshold_routing_ratio=0.35)
    assert len(alerts) >= 1
    routing_alert = next((a for a in alerts if a.severity == NudgeSeverity.WARNING), None)
    assert routing_alert is not None
    assert "Routing overhead is 60.0%" in routing_alert.message
    assert routing_alert.routing_ratio == 0.6


def test_doctor_nudge_alert_repetitive_handoffs() -> None:
    gov = SharedTokenBudgetGovernor(session_id="sess-gov-07", shared_token_ceiling=50_000)

    # Trigger 5 handoffs
    for i in range(5):
        gov.record_consumption(
            agent_role=f"agent-{i}",
            category=ConsumptionCategory.ROUTING_OVERHEAD,
            prompt_tokens=100,
            completion_tokens=50,
            metadata={"is_handoff": True},
        )

    alerts = gov.evaluate_doctor_nudge(max_handoffs=5)
    crit_alert = next((a for a in alerts if a.severity == NudgeSeverity.CRITICAL), None)
    assert crit_alert is not None
    assert "Repetitive agent handoffs detected (5 >= 5)" in crit_alert.message
    assert crit_alert.handoff_count == 5


def test_governor_reset() -> None:
    gov = SharedTokenBudgetGovernor(session_id="sess-gov-08")
    gov.register_role_budget(RoleBudgetSpec("bot", 5000))
    gov.record_consumption("bot", ConsumptionCategory.EXECUTION_PAYLOAD, 100, 100)

    gov.reset()
    snap = gov.get_snapshot()
    assert snap.total_tokens_spent == 0
    assert len(snap.role_budgets) == 0
    assert len(snap.role_usage) == 0
    assert len(snap.active_alerts) == 0
