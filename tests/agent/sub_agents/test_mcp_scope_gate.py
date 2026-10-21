"""Tests for Employee/Agent-Scoped MCP Tool Discovery Gate.

[INPUT]
- myrm_agent_harness.agent.sub_agents.mcp_scope_gate.*

[OUTPUT]
- Pytest test cases verifying employee-scoped MCP discovery, fail-closed isolation, and invocation protection

[POS]
myrm-agent-harness/tests/agent/sub_agents/test_mcp_scope_gate.py
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.sub_agents.mcp_scope_gate import (
    EmployeeScopedMcpDiscoveryGate,
    EmployeeToolScopePolicy,
    EmployeeToolScopeViolationError,
    ScopedMcpFilterVerdict,
)


def test_unregistered_agent_fail_closed() -> None:
    gate = EmployeeScopedMcpDiscoveryGate()
    discovered = [
        ("github", "create_issue", "Create GitHub issue"),
        ("slack", "send_message", "Send Slack message"),
    ]

    verdict: ScopedMcpFilterVerdict = gate.filter_discovered_tools("agent-unknown", discovered)
    assert verdict.total_discovered == 2
    assert verdict.allowed_count == 0
    assert verdict.blocked_count == 2
    assert len(verdict.allowed_tools) == 0
    assert "Fail-Closed" in verdict.blocked_tools[0].reason


def test_filter_discovered_tools_server_scoping() -> None:
    gate = EmployeeScopedMcpDiscoveryGate()

    # Agent A: Coder (GitHub only)
    policy_a = EmployeeToolScopePolicy(
        agent_id="agent-coder-a",
        allowed_mcp_servers=["github"],
        tool_allowlist_map={},  # All tools on github allowed
    )
    gate.register_policy(policy_a)

    # Agent B: DBA (Postgres only)
    policy_b = EmployeeToolScopePolicy(
        agent_id="agent-dba-b",
        allowed_mcp_servers=["postgres"],
        tool_allowlist_map={},
    )
    gate.register_policy(policy_b)

    pool = [
        ("github", "create_pr", "Open PR"),
        ("github", "merge_pr", "Merge PR"),
        ("postgres", "query_table", "Execute read-only SQL"),
        ("postgres", "drop_table", "Drop SQL table"),
    ]

    verdict_a = gate.filter_discovered_tools("agent-coder-a", pool)
    assert verdict_a.allowed_count == 2
    assert verdict_a.blocked_count == 2
    assert {t.tool_name for t in verdict_a.allowed_tools} == {"create_pr", "merge_pr"}
    assert {t.tool_name for t in verdict_a.blocked_tools} == {"query_table", "drop_table"}

    verdict_b = gate.filter_discovered_tools("agent-dba-b", pool)
    assert verdict_b.allowed_count == 2
    assert verdict_b.blocked_count == 2
    assert {t.tool_name for t in verdict_b.allowed_tools} == {"query_table", "drop_table"}
    assert {t.tool_name for t in verdict_b.blocked_tools} == {"create_pr", "merge_pr"}


def test_filter_fine_grained_tool_allowlist() -> None:
    gate = EmployeeScopedMcpDiscoveryGate()

    # Agent C: Junior Analyst (Postgres allowed, but only read query_table, drop_table blocked)
    policy_c = EmployeeToolScopePolicy(
        agent_id="agent-analyst-c",
        allowed_mcp_servers=["postgres"],
        tool_allowlist_map={"postgres": ["query_table"]},
    )
    gate.register_policy(policy_c)

    pool = [
        ("postgres", "query_table", "Read SQL"),
        ("postgres", "drop_table", "Destructive Drop SQL"),
    ]

    verdict = gate.filter_discovered_tools("agent-analyst-c", pool)
    assert verdict.allowed_count == 1
    assert verdict.blocked_count == 1
    assert verdict.allowed_tools[0].tool_name == "query_table"
    assert verdict.blocked_tools[0].tool_name == "drop_table"
    assert "not in allowlist" in verdict.blocked_tools[0].reason


def test_verify_tool_invocation_success_and_violation() -> None:
    gate = EmployeeScopedMcpDiscoveryGate()
    policy = EmployeeToolScopePolicy(
        agent_id="agent-finance-01",
        allowed_mcp_servers=["stripe"],
        tool_allowlist_map={"stripe": ["get_invoice"]},
    )
    gate.register_policy(policy)

    # 1. Allowed tool invocation
    check_ok = gate.verify_tool_invocation("agent-finance-01", "stripe", "get_invoice")
    assert check_ok.is_allowed is True

    # 2. Blocked tool invocation on allowed server -> raises exception
    with pytest.raises(EmployeeToolScopeViolationError) as exc_info:
        gate.verify_tool_invocation("agent-finance-01", "stripe", "refund_charge")
    assert "refund_charge" in str(exc_info.value)

    # 3. Blocked server invocation -> raises exception
    with pytest.raises(EmployeeToolScopeViolationError) as exc_info2:
        gate.verify_tool_invocation("agent-finance-01", "aws", "terminate_instance")
    assert "aws" in str(exc_info2.value)
