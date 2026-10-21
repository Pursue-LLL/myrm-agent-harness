"""
[POS] tests/unit/test_readonly_research_sandbox_suite.py
[INPUT] myrm_agent_harness.core.security.readonly_research_sandbox
[OUTPUT] Unit test suite for the Read-Only Autonomous Research Lease

Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import time

import pytest

from myrm_agent_harness.core.security.readonly_research_sandbox import (
    DEFAULT_READ_ONLY_TOOLS,
    LeaseStatusEnum,
    ReadOnlyLeaseManager,
    ReadOnlyResearchSandboxFacade,
    ResearchModeEnum,
)
from myrm_agent_harness.core.security.tool_registry import BUILTIN_TOOL_NAMES, resolve_safety_metadata


def test_default_read_only_tools_stay_in_sync_with_the_safety_registry() -> None:
    """The allow-list is hand-listed, so a rename or flag change in the registry must fail here, not at runtime."""
    for tool in DEFAULT_READ_ONLY_TOOLS:
        assert tool in BUILTIN_TOOL_NAMES, f"{tool} is not a built-in tool"
        meta = resolve_safety_metadata(tool)
        assert meta.is_read_only, f"{tool} is not flagged read-only"
        assert not meta.is_destructive, f"{tool} is flagged destructive"


def test_readonly_lease_manager_lifecycle_and_tool_stripping() -> None:
    """Test read-only lease granting, tool physical stripping, revocation, and expiration."""
    mgr = ReadOnlyLeaseManager(default_ttl_seconds=10.0)
    session_id = "sess-lease-01"

    # 1. Grant lease
    lease = mgr.grant_lease(session_id, ResearchModeEnum.AUTONOMOUS_RESEARCH)
    assert lease.status == LeaseStatusEnum.ACTIVE
    assert lease.research_mode == ResearchModeEnum.AUTONOMOUS_RESEARCH
    assert lease.allowed_tools == DEFAULT_READ_ONLY_TOOLS

    # 2. Every default read tool passes
    for tool in DEFAULT_READ_ONLY_TOOLS:
        allowed, _ = mgr.evaluate_tool(session_id, tool)
        assert allowed is True, tool

    # 3. Registry-destructive tools are physically stripped
    for tool in ("file_write_tool", "file_edit_tool", "bash_code_execute_tool"):
        allowed_d, reason_d = mgr.evaluate_tool(session_id, tool)
        assert allowed_d is False, tool
        assert "physically stripped by Read-Only Research Lease" in reason_d

    # 4. Non-destructive tools outside the allow-list are blocked with the whitelist wording
    for tool in ("todo_write", "memory_search_tool", "mcp__mail__send", "arbitrary_custom_mutator"):
        allowed_u, reason_u = mgr.evaluate_tool(session_id, tool)
        assert allowed_u is False, tool
        assert "not in the safe read-only whitelist" in reason_u

    # 5. Revoke lease
    rev_lease = mgr.revoke_lease(session_id)
    assert rev_lease is not None
    assert rev_lease.status == LeaseStatusEnum.REVOKED

    # Once revoked, the lease is forgotten and standard dispatch is permitted
    assert mgr.get_lease(session_id) is None
    assert mgr.revoke_lease(session_id) is None
    allowed_post, _ = mgr.evaluate_tool(session_id, "file_write_tool")
    assert allowed_post is True

    # 6. Expiration test
    mgr.grant_lease("sess-exp", ResearchModeEnum.BACKGROUND_STUDY, ttl_seconds=0.01)
    exp_lease = mgr.get_lease("sess-exp", current_time=time.time() + 100)
    assert exp_lease is not None
    assert exp_lease.status == LeaseStatusEnum.EXPIRED
    allowed_expired, _ = mgr.evaluate_tool("sess-exp", "file_write_tool")
    assert allowed_expired is True


@pytest.mark.parametrize(
    ("tool", "expected"),
    [("memory_search_tool", True), ("file_read_tool", False)],
)
def test_custom_allowed_tools_replace_the_default_allow_list(tool: str, expected: bool) -> None:
    mgr = ReadOnlyLeaseManager()
    mgr.grant_lease("sess-custom", custom_allowed_tools=("memory_search_tool",))
    allowed, _ = mgr.evaluate_tool("sess-custom", tool)
    assert allowed is expected


def test_facade_grants_enforces_and_counts_leases() -> None:
    """The facade is the process-wide entry point: it grants, enforces and revokes leases and counts each step."""
    facade = ReadOnlyResearchSandboxFacade()
    session_id = "sess-facade-ro"

    lease = facade.grant_research_lease(session_id, ResearchModeEnum.AUTONOMOUS_RESEARCH)
    assert lease.status == LeaseStatusEnum.ACTIVE
    assert facade.get_lease(session_id) == lease

    assert facade.evaluate_tool(session_id, "file_read_tool")[0] is True
    assert facade.evaluate_tool(session_id, "bash_code_execute_tool")[0] is False

    metrics = facade.get_metrics()
    assert metrics.total_leases_granted == 1
    assert metrics.active_leases_count == 1
    assert metrics.write_attempts_blocked == 1

    revoked = facade.revoke_lease(session_id)
    assert revoked is not None
    assert revoked.status == LeaseStatusEnum.REVOKED
    assert facade.get_lease(session_id) is None
    assert facade.evaluate_tool(session_id, "bash_code_execute_tool")[0] is True

    metrics = facade.get_metrics()
    assert metrics.active_leases_count == 0
    assert metrics.leases_revoked_count == 1


def test_leases_of_different_sessions_do_not_affect_each_other() -> None:
    facade = ReadOnlyResearchSandboxFacade()
    facade.grant_research_lease("sess-a")

    assert facade.evaluate_tool("sess-a", "file_write_tool")[0] is False
    assert facade.evaluate_tool("sess-b", "file_write_tool")[0] is True

    facade.revoke_lease("sess-b")

    assert facade.get_lease("sess-a") is not None
