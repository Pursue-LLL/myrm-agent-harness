"""Unit tests for Orchestrator Scope Guardrails and Safe Team Design Mode (Item 37).

[INPUT]
- myrm_agent_harness.agent.coordination.scope_guardrails::{
    MemberScopeCandidate,
    SafeTeamDesignConfig,
    ScopeGuardrailsEngine,
    ViolationSeverity,
    ViolationType,
  }

[OUTPUT]
- Pytest cases verifying least-privilege tool pruning, globally forbidden tool defense,
  fan-out cap enforcement, and custom security configuration.

[POS]
- myrm-agent-harness/tests/agent/coordination/test_scope_guardrails.py
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.coordination.scope_guardrails import (
    MemberScopeCandidate,
    SafeTeamDesignConfig,
    ScopeGuardrailsEngine,
    ViolationSeverity,
    ViolationType,
)


@pytest.fixture
def engine() -> ScopeGuardrailsEngine:
    return ScopeGuardrailsEngine()


def test_safe_team_design_all_passed(engine: ScopeGuardrailsEngine) -> None:
    candidates = [
        MemberScopeCandidate(
            role_key="orchestrator",
            display_name="Squad Lead",
            requested_tools=["spawn_subagent", "delegate_task", "roster_read"],
        ),
        MemberScopeCandidate(
            role_key="coder",
            display_name="Backend Engineer",
            requested_tools=["file_read", "file_write", "test_runner"],
        ),
        MemberScopeCandidate(
            role_key="researcher",
            display_name="Market Analyst",
            requested_tools=["web_search", "web_fetch", "file_read"],
        ),
    ]

    result = engine.evaluate_team_design(candidates)
    assert result.is_safe is True
    assert result.fanout_capped is False
    assert result.original_member_count == 3
    assert result.approved_member_count == 3
    assert len(result.violations) == 0
    assert result.sanitized_tools_map["coder"] == ["file_read", "file_write", "test_runner"]
    assert "passed all scope guardrails" in result.audit_summary


def test_globally_forbidden_tool_defense(engine: ScopeGuardrailsEngine) -> None:
    candidates = [
        MemberScopeCandidate(
            role_key="coder",
            display_name="Rogue Coder",
            requested_tools=["file_read", "system_exec", "raw_bash_root"],
        ),
    ]

    result = engine.evaluate_team_design(candidates)
    assert result.is_safe is False
    assert len(result.violations) == 2
    assert all(v.violation_type == ViolationType.FORBIDDEN_TOOL for v in result.violations)
    assert all(v.severity == ViolationSeverity.BLOCKER for v in result.violations)
    # High risk tools must be stripped from sanitized output
    assert result.sanitized_tools_map["coder"] == ["file_read"]
    assert "flagged with 2 blocker" in result.audit_summary


def test_role_least_privilege_boundary_pruning(engine: ScopeGuardrailsEngine) -> None:
    candidates = [
        MemberScopeCandidate(
            role_key="researcher",
            display_name="Scout",
            # researcher allowlist doesn't include file_write
            requested_tools=["web_search", "file_write", "web_fetch"],
        ),
    ]

    result = engine.evaluate_team_design(candidates)
    # Warnings do not block is_safe, but excess tools are pruned
    assert result.is_safe is True
    assert len(result.violations) == 1
    violation = result.violations[0]
    assert violation.violation_type == ViolationType.ROLE_SCOPE_EXCEEDED
    assert violation.severity == ViolationSeverity.WARNING
    assert violation.tool_name == "file_write"
    assert result.sanitized_tools_map["researcher"] == ["web_search", "web_fetch"]


def test_fanout_cap_truncation(engine: ScopeGuardrailsEngine) -> None:
    # 7 candidates while default max_fanout_cap is 5
    candidates = [
        MemberScopeCandidate(role_key="coder", display_name=f"Worker {i}", requested_tools=["file_read"])
        for i in range(7)
    ]

    result = engine.evaluate_team_design(candidates)
    assert result.fanout_capped is True
    assert result.is_safe is False
    assert result.original_member_count == 7
    assert result.approved_member_count == 5
    assert any(v.violation_type == ViolationType.FANOUT_LIMIT_EXCEEDED for v in result.violations)


def test_custom_security_configuration(engine: ScopeGuardrailsEngine) -> None:
    custom_cfg = SafeTeamDesignConfig(
        max_fanout_cap=2,
        forbidden_tools=frozenset({"custom_danger_tool"}),
        role_tool_allowlists={"custom_role": frozenset({"tool_a", "tool_b"})},
    )

    candidates = [
        MemberScopeCandidate(
            role_key="custom_role",
            display_name="Specialist 1",
            requested_tools=["tool_a", "tool_c", "custom_danger_tool"],
        ),
        MemberScopeCandidate(
            role_key="custom_role",
            display_name="Specialist 2",
            requested_tools=["tool_b"],
        ),
        MemberScopeCandidate(
            role_key="custom_role",
            display_name="Specialist 3",
            requested_tools=["tool_a"],
        ),
    ]

    result = engine.evaluate_team_design(candidates, config=custom_cfg)
    assert result.fanout_capped is True
    assert result.approved_member_count == 2
    # Specialist 1 should have tool_c pruned (role scope) and custom_danger_tool blocked
    violations = result.violations
    assert any(v.violation_type == ViolationType.FORBIDDEN_TOOL for v in violations)
    assert any(v.violation_type == ViolationType.ROLE_SCOPE_EXCEEDED for v in violations)
    assert any(v.violation_type == ViolationType.FANOUT_LIMIT_EXCEEDED for v in violations)


def test_empty_candidates_handled_gracefully(engine: ScopeGuardrailsEngine) -> None:
    result = engine.evaluate_team_design([])
    assert result.is_safe is True
    assert result.original_member_count == 0
    assert result.approved_member_count == 0
    assert len(result.violations) == 0
    assert len(result.sanitized_tools_map) == 0
