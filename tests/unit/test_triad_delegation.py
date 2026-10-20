"""Unit tests for TriadDelegationToken and PrivilegeIntersectionGuard.

[POS]
Validates immutable triad identity tokens, least-privilege intersection
calculation, subagent containment, and guard assertion gates.
"""

from __future__ import annotations

import time
import pytest

from myrm_agent_harness.agent.security.delegation.models import (
    SubjectIdentity,
    SubjectType,
    TriadDelegationToken,
)
from myrm_agent_harness.agent.security.delegation.guard import (
    PrivilegeAmplificationBlockedError,
    PrivilegeIntersectionGuard,
)


def test_triad_delegation_intersection_calculation() -> None:
    """Test that effective privilege strictly equals the intersection of requester and agent."""
    requester = SubjectIdentity(
        subject_id="user_alice",
        subject_type=SubjectType.HUMAN,
        display_name="Alice (Viewer)",
        scopes=frozenset({"workspace:read", "ssh:exec:read"}),
    )
    agent = SubjectIdentity(
        subject_id="agent_devops",
        subject_type=SubjectType.AGENT,
        display_name="DevOps Bot",
        scopes=frozenset({"workspace:read", "ssh:exec:read", "ssh:exec:write", "db:alter"}),
    )

    # 1. Base intersection without approver
    token = TriadDelegationToken(initial_requester=requester, executor_agent=agent)
    effective = token.effective_scopes
    assert effective == frozenset({"workspace:read", "ssh:exec:read"})
    assert token.has_scope("ssh:exec:read") is True
    assert token.has_scope("ssh:exec:write") is False  # Blocked! Alice lacks write privilege

    # 2. Approver endorses write action
    approver = SubjectIdentity(
        subject_id="user_bob_admin",
        subject_type=SubjectType.HUMAN,
        display_name="Bob (Lead)",
        scopes=frozenset({"ssh:exec:write"}),
    )
    approved_token = TriadDelegationToken(
        initial_requester=requester,
        executor_agent=agent,
        business_approver=approver,
    )
    assert approved_token.has_scope("ssh:exec:write") is True


def test_subagent_privilege_containment() -> None:
    """Test that deriving a subagent automatically narrows the privilege boundary."""
    requester = SubjectIdentity(
        subject_id="user_alice",
        subject_type=SubjectType.HUMAN,
        display_name="Alice",
        scopes=frozenset({"workspace:read", "ssh:exec:read"}),
    )
    parent_agent = SubjectIdentity(
        subject_id="agent_orchestrator",
        subject_type=SubjectType.AGENT,
        display_name="Orchestrator",
        scopes=frozenset({"workspace:read", "ssh:exec:read"}),
    )
    parent_token = TriadDelegationToken(initial_requester=requester, executor_agent=parent_agent)

    subagent_identity = SubjectIdentity(
        subject_id="subagent_researcher",
        subject_type=SubjectType.AGENT,
        display_name="Researcher Subagent",
        scopes=frozenset({"workspace:read"}),  # Only workspace:read
    )
    child_token = parent_token.derive_subagent_token(subagent_identity)

    # Child scopes should be narrowed to workspace:read only
    assert child_token.effective_scopes == frozenset({"workspace:read"})
    assert child_token.has_scope("ssh:exec:read") is False


def test_privilege_intersection_guard_enforcement() -> None:
    """Test PrivilegeIntersectionGuard raising PrivilegeAmplificationBlockedError."""
    requester = SubjectIdentity(
        subject_id="user_charlie",
        subject_type=SubjectType.HUMAN,
        display_name="Charlie (Guest)",
        scopes=frozenset({"workspace:read"}),
    )
    agent = SubjectIdentity(
        subject_id="agent_power",
        subject_type=SubjectType.AGENT,
        display_name="Power Agent",
        scopes=frozenset({"workspace:read", "cloud:deploy"}),
    )
    token = TriadDelegationToken(initial_requester=requester, executor_agent=agent)

    # 1. Allowed scope passes
    PrivilegeIntersectionGuard.assert_scope_allowed(token, "workspace:read")
    assert PrivilegeIntersectionGuard.is_scope_allowed(token, "workspace:read") is True

    # 2. Unauthorized scope raises PrivilegeAmplificationBlockedError
    with pytest.raises(PrivilegeAmplificationBlockedError) as exc_info:
        PrivilegeIntersectionGuard.assert_scope_allowed(token, "cloud:deploy", action_name="deploy_prod")
    err = exc_info.value
    assert err.required_scope == "cloud:deploy"
    assert err.initial_requester_id == "user_charlie"
    diag = err.to_diagnostic_info()
    assert diag["privilege_amplification_blocked"] is True

    # 3. None token raises
    with pytest.raises(PrivilegeAmplificationBlockedError):
        PrivilegeIntersectionGuard.assert_scope_allowed(None, "workspace:read")
