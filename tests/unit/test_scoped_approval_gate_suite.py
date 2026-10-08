"""
[POS] tests/unit/test_scoped_approval_gate_suite.py
Unit tests for Scoped Approval Grant and Risk-Tiered Gate Suite.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from myrm_agent_harness.core.security.scoped_approval import (
    ActionRiskTier,
    GateDecision,
    GrantScope,
    RiskEvaluationRequest,
    RiskTieredGateRouter,
    ScopedApprovalGateFacade,
    ScopedGrantLeaseEngine,
)


def test_lease_engine_scopes_and_redemption() -> None:
    engine = ScopedGrantLeaseEngine()
    now = 1000.0

    # 1. ONCE Scope
    once_lease = engine.issue_grant(
        tool_name="shell_exec",
        scope=GrantScope.ONCE,
        agent_id="agent-01",
        session_id="sess-01",
        current_time=now,
    )
    assert engine.find_active_grant("shell_exec", "agent-01", "sess-01", current_time=now) is not None
    # Redeem once
    res1 = engine.redeem_grant(once_lease.grant_id, "shell_exec", "agent-01", "sess-01", current_time=now)
    assert res1 is not None
    assert res1[0].use_count == 1
    # Second search should find no active grant for ONCE
    assert engine.find_active_grant("shell_exec", "agent-01", "sess-01", current_time=now) is None

    # 2. TASK Scope
    task_lease = engine.issue_grant(
        tool_name="file_write",
        scope=GrantScope.TASK,
        agent_id="agent-01",
        session_id="sess-01",
        task_id="task-abc",
        current_time=now,
    )
    assert task_lease.grant_id.startswith("grant-")
    # Active under same task_id
    assert (
        engine.find_active_grant("file_write", "agent-01", "sess-01", task_id="task-abc", current_time=now)
        is not None
    )
    # Inactive under different task_id
    assert (
        engine.find_active_grant("file_write", "agent-01", "sess-01", task_id="task-xyz", current_time=now)
        is None
    )

    # 3. 24H Scope expiration
    day_lease = engine.issue_grant(
        tool_name="git_push",
        scope=GrantScope.HOURS_24,
        agent_id="agent-01",
        session_id="sess-01",
        current_time=now,
    )
    assert day_lease.grant_id.startswith("grant-")
    assert engine.find_active_grant("git_push", "agent-01", "sess-01", current_time=now + 3600.0) is not None
    # Expired after 24h + 1s
    assert (
        engine.find_active_grant("git_push", "agent-01", "sess-01", current_time=now + 86401.0) is None
    )


def test_risk_tiered_gate_router() -> None:
    router = RiskTieredGateRouter(
        deny_tools=("rm_rf", "kill_system"),
        always_allow_tools=("echo", "clock"),
        always_ask_tools=("transfer_money",),
        auto_allow_low_risk_write=False,
    )

    # 1. Denied
    req_deny = RiskEvaluationRequest(
        tool_name="rm_rf",
        risk_tier=ActionRiskTier.HIGH_RISK_WRITE,
        agent_id="agent-01",
        session_id="sess-01",
    )
    res_deny = router.evaluate(req_deny)
    assert res_deny.decision == GateDecision.DENY

    # 2. Always Allow
    req_echo = RiskEvaluationRequest(
        tool_name="echo",
        risk_tier=ActionRiskTier.LOW_RISK_WRITE,
        agent_id="agent-01",
        session_id="sess-01",
    )
    res_echo = router.evaluate(req_echo)
    assert res_echo.decision == GateDecision.ALLOW

    # 3. Read Only silent allow
    req_ro = RiskEvaluationRequest(
        tool_name="query_knowledge_base",
        risk_tier=ActionRiskTier.READ_ONLY,
        agent_id="agent-01",
        session_id="sess-01",
    )
    res_ro = router.evaluate(req_ro)
    assert res_ro.decision == GateDecision.ALLOW
    assert res_ro.requires_hitl_prompt is False

    # 4. Low risk write mandates ask when auto_allow is False
    req_low = RiskEvaluationRequest(
        tool_name="append_log",
        risk_tier=ActionRiskTier.LOW_RISK_WRITE,
        agent_id="agent-01",
        session_id="sess-01",
    )
    res_low = router.evaluate(req_low)
    assert res_low.decision == GateDecision.ASK
    assert res_low.requires_hitl_prompt is True

    # 5. Irreversible egress mandates ask
    req_egress = RiskEvaluationRequest(
        tool_name="send_telegram_broadcast",
        risk_tier=ActionRiskTier.IRREVERSIBLE_EGRESS,
        agent_id="agent-01",
        session_id="sess-01",
    )
    res_egress = router.evaluate(req_egress)
    assert res_egress.decision == GateDecision.ASK


def test_facade_end_to_end_and_ledger() -> None:
    facade = ScopedApprovalGateFacade()
    now = 5000.0

    # Evaluate high risk operation without lease -> ASK
    req_high = RiskEvaluationRequest(
        tool_name="deploy_container",
        risk_tier=ActionRiskTier.HIGH_RISK_WRITE,
        agent_id="deployer-agent",
        session_id="sess-prod",
        task_id="task-deploy-1",
    )
    res1 = facade.evaluate_and_process(req_high, current_time=now)
    assert res1.decision == GateDecision.ASK
    assert facade.metrics.asks_required_total == 1

    # User issues TASK scope grant
    lease = facade.issue_grant(
        tool_name="deploy_container",
        scope=GrantScope.TASK,
        agent_id="deployer-agent",
        session_id="sess-prod",
        task_id="task-deploy-1",
        current_time=now,
    )
    assert facade.metrics.grants_issued_total == 1
    assert len(facade.list_active_grants(current_time=now)) == 1

    # Re-evaluate with active task grant -> ALLOW
    res2 = facade.evaluate_and_process(req_high, current_time=now)
    assert res2.decision == GateDecision.ALLOW
    assert res2.matched_grant_id == lease.grant_id
    assert facade.metrics.grant_redemptions_total == 1

    # Check ledger
    ledger = facade.get_audit_ledger()
    assert len(ledger) == 1
    assert ledger[0].grant_id == lease.grant_id

    # Revoke all leases for this session
    revoked_count = facade.revoke_all(session_id="sess-prod")
    assert revoked_count == 1
    assert facade.metrics.grants_revoked_total == 1
    assert len(facade.list_active_grants(current_time=now)) == 0
