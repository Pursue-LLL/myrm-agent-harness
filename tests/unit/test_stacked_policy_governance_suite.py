"""Unit tests for Three-Tier Stacked Policy Governance and Downgrade Gate Suite."""

from __future__ import annotations

from myrm_agent_harness.core.security.stacked_policy_governance import (
    DowngradeGate,
    DowngradeGateSpec,
    PolicyRule,
    ThreeTierStackedPolicyStack,
)


def test_stacked_policy_precedence_and_short_circuit() -> None:
    """Test precedence across Session, Agent, and Server tiers with short-circuiting."""
    stack = ThreeTierStackedPolicyStack()

    # 1. Server tier baseline rule
    stack.add_server_rule(
        PolicyRule(
            tier="server",
            name="server_forbid_dangerous_shell",
            phase="tool_call",
            action="deny",
            target_pattern="rm -rf *",
            reason="Enterprise baseline blocks destructive deletion commands",
        )
    )

    # 2. Agent tier spec rule
    stack.add_agent_rule(
        PolicyRule(
            tier="agent",
            name="agent_readonly_file_write",
            phase="tool_call",
            action="deny",
            target_pattern="file_write",
            reason="Read-only analysis agent forbidden from writing files",
            agent_id="agent_analyst",
        )
    )

    # 3. Session tier dynamic rule (Short-circuits before agent/server)
    stack.add_session_rule(
        PolicyRule(
            tier="session",
            name="session_block_network",
            phase="tool_call",
            action="deny",
            target_pattern="net_fetch",
            reason="Current user session forbidden from making external network calls",
            session_id="sess_1001",
        )
    )

    # Evaluation A: Session rule matches net_fetch -> DENY at session tier
    res_sess = stack.evaluate(
        phase="tool_call",
        target="net_fetch",
        session_id="sess_1001",
        agent_id="agent_analyst",
    )
    assert res_sess.decision == "deny"
    assert res_sess.matched_tier == "session"
    assert res_sess.matched_rule == "session_block_network"

    # Evaluation B: Agent rule matches file_write -> DENY at agent tier
    res_agent = stack.evaluate(
        phase="tool_call",
        target="file_write",
        session_id="sess_1001",
        agent_id="agent_analyst",
    )
    assert res_agent.decision == "deny"
    assert res_agent.matched_tier == "agent"

    # Evaluation C: Server baseline matches rm -rf * -> DENY at server tier
    res_server = stack.evaluate(
        phase="tool_call",
        target="rm -rf *",
        session_id="sess_1001",
        agent_id="agent_analyst",
    )
    assert res_server.decision == "deny"
    assert res_server.matched_tier == "server"

    # Evaluation D: Safe tool call matches nothing -> ALLOW
    res_safe = stack.evaluate(
        phase="tool_call",
        target="read_file",
        session_id="sess_1001",
        agent_id="agent_analyst",
    )
    assert res_safe.decision == "allow"
    assert res_safe.requires_approval is False


def test_ask_card_emission_and_lifecycle_phase() -> None:
    """Test emitting interactive MCP-style ASK cards for sensitive operations."""
    stack = ThreeTierStackedPolicyStack()
    stack.add_session_rule(
        PolicyRule(
            tier="session",
            name="confirm_db_drop",
            phase="tool_call",
            action="ask",
            target_pattern="drop_table_*",
            reason="Dropping table is sensitive and requires confirmation",
            session_id="sess_db_admin",
        )
    )

    res_ask = stack.evaluate(
        phase="tool_call",
        target="drop_table_customers",
        session_id="sess_db_admin",
    )
    assert res_ask.decision == "ask"
    assert res_ask.requires_approval is True
    assert res_ask.ask_card is not None
    assert res_ask.ask_card.prompt_title == "Session Approval: confirm_db_drop"
    assert res_ask.ask_card.target_operation == "drop_table_customers"


def test_downgrade_gate_tokenomics_fallback() -> None:
    """Test soft threshold downgrade to economical model and hard limit blocking."""
    gate = DowngradeGate(
        DowngradeGateSpec(
            soft_limit_tokens=1000,
            soft_limit_cost=1.0,
            hard_limit_cost=5.0,
            primary_model="claude-3-7-sonnet",
            fallback_model="gpt-4o-mini",
        )
    )

    # 1. Initial nominal usage: on primary model
    st1 = gate.record_usage("sess_01", additional_tokens=200, additional_cost=0.1)
    assert st1.is_downgraded is False
    assert st1.is_hard_blocked is False
    assert st1.active_model == "claude-3-7-sonnet"

    # 2. Exceeding soft token limit: triggers graceful downgrade
    st2 = gate.record_usage("sess_01", additional_tokens=900, additional_cost=0.5)
    assert st2.is_downgraded is True
    assert st2.is_hard_blocked is False
    assert st2.active_model == "gpt-4o-mini"
    assert "gracefully downgraded" in st2.message

    # 3. Exceeding hard cost limit: triggers hard suspension
    st3 = gate.record_usage("sess_01", additional_tokens=500, additional_cost=4.5)
    assert st3.is_hard_blocked is True
    assert "Hard limit" in st3.message
