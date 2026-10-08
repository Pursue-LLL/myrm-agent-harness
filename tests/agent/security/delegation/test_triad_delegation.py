"""Tests for the triad delegation token, the privilege intersection guard and the session accessor."""

from __future__ import annotations

import time
from collections.abc import Iterator

import pytest

# ``agent.middlewares`` re-exports the accessor; importing it is what a clean checkout once failed on.
from myrm_agent_harness.agent.middlewares import get_delegation_token
from myrm_agent_harness.agent.middlewares._session_context import set_delegation_token
from myrm_agent_harness.agent.security.delegation.guard import (
    PrivilegeAmplificationBlockedError,
    PrivilegeIntersectionGuard,
)
from myrm_agent_harness.agent.security.delegation.models import (
    SubjectIdentity,
    SubjectType,
    TriadDelegationToken,
)


def _human(subject_id: str, *scopes: str) -> SubjectIdentity:
    return SubjectIdentity(
        subject_id=subject_id,
        subject_type=SubjectType.HUMAN,
        display_name=subject_id,
        scopes=frozenset(scopes),
    )


def _agent(subject_id: str, *scopes: str) -> SubjectIdentity:
    return SubjectIdentity(
        subject_id=subject_id,
        subject_type=SubjectType.AGENT,
        display_name=subject_id,
        scopes=frozenset(scopes),
    )


@pytest.fixture(autouse=True)
def _no_published_token() -> Iterator[None]:
    """Keep the context-local token from leaking between tests of this module."""
    set_delegation_token(None)
    yield
    set_delegation_token(None)


def test_effective_scopes_are_the_requester_agent_intersection() -> None:
    requester = _human("user_alice", "workspace:read", "ssh:exec:read")
    agent = _agent("agent_devops", "workspace:read", "ssh:exec:read", "ssh:exec:write", "db:alter")

    token = TriadDelegationToken(initial_requester=requester, executor_agent=agent)

    assert token.effective_scopes == frozenset({"workspace:read", "ssh:exec:read"})
    assert token.has_scope("ssh:exec:read") is True
    assert token.has_scope("ssh:exec:write") is False


def test_business_approver_extends_only_scopes_the_agent_holds() -> None:
    requester = _human("user_alice", "workspace:read")
    agent = _agent("agent_devops", "workspace:read", "ssh:exec:write")
    approver = _human("user_bob", "ssh:exec:write", "db:drop")

    token = TriadDelegationToken(initial_requester=requester, executor_agent=agent, business_approver=approver)

    assert token.has_scope("ssh:exec:write") is True
    assert token.has_scope("db:drop") is False


def test_wildcard_scope_grants_every_scope() -> None:
    token = TriadDelegationToken(initial_requester=_human("root", "*"), executor_agent=_agent("agent_any", "*"))

    assert token.has_scope("anything:at:all") is True


def test_expired_token_grants_nothing() -> None:
    token = TriadDelegationToken(
        initial_requester=_human("user_alice", "workspace:read"),
        executor_agent=_agent("agent_devops", "workspace:read"),
        created_at=time.time() - 1_000.0,
        token_ttl_seconds=600.0,
    )

    assert token.is_expired is True
    assert token.has_scope("workspace:read") is False
    assert PrivilegeIntersectionGuard.is_scope_allowed(token, "workspace:read") is False
    with pytest.raises(PrivilegeAmplificationBlockedError, match="expired"):
        PrivilegeIntersectionGuard.assert_scope_allowed(token, "workspace:read")


def test_subagent_token_is_narrowed_to_the_parent_intersection() -> None:
    approver = _human("user_bob", "ssh:exec:read")
    parent = TriadDelegationToken(
        initial_requester=_human("user_alice", "workspace:read", "ssh:exec:read"),
        executor_agent=_agent("agent_orchestrator", "workspace:read", "ssh:exec:read"),
        business_approver=approver,
    )
    researcher = _agent("subagent_researcher", "workspace:read", "cloud:deploy")

    child = parent.derive_subagent_token(researcher)

    assert child.effective_scopes == frozenset({"workspace:read"})
    assert child.has_scope("ssh:exec:read") is False
    assert child.has_scope("cloud:deploy") is False
    assert child.executor_agent.subject_type is SubjectType.AGENT
    assert child.initial_requester == parent.initial_requester
    assert child.business_approver == approver
    assert child.created_at == parent.created_at


def test_guard_blocks_a_scope_outside_the_intersection() -> None:
    token = TriadDelegationToken(
        initial_requester=_human("user_charlie", "workspace:read"),
        executor_agent=_agent("agent_power", "workspace:read", "cloud:deploy"),
    )

    PrivilegeIntersectionGuard.assert_scope_allowed(token, "workspace:read")
    assert PrivilegeIntersectionGuard.is_scope_allowed(token, "workspace:read") is True

    with pytest.raises(PrivilegeAmplificationBlockedError) as blocked:
        PrivilegeIntersectionGuard.assert_scope_allowed(token, "cloud:deploy", action_name="deploy_prod")

    assert blocked.value.required_scope == "cloud:deploy"
    assert blocked.value.initial_requester_id == "user_charlie"
    assert blocked.value.executor_agent_id == "agent_power"
    assert blocked.value.to_diagnostic_info() == {
        "privilege_amplification_blocked": True,
        "required_scope": "cloud:deploy",
        "initial_requester_id": "user_charlie",
        "executor_agent_id": "agent_power",
        "effective_scopes": ["workspace:read"],
    }


def test_guard_fails_closed_without_a_token() -> None:
    assert PrivilegeIntersectionGuard.is_scope_allowed(None, "workspace:read") is False
    with pytest.raises(PrivilegeAmplificationBlockedError) as blocked:
        PrivilegeIntersectionGuard.assert_scope_allowed(None, "workspace:read", action_name="read_file")

    assert blocked.value.initial_requester_id == "anonymous"
    assert blocked.value.effective_scopes == frozenset()


def test_subject_identity_round_trips_through_a_dict() -> None:
    identity = _agent("agent_devops", "workspace:read", "ssh:exec:read")

    payload = identity.to_dict()

    assert payload == {
        "subject_id": "agent_devops",
        "subject_type": "agent",
        "display_name": "agent_devops",
        "scopes": ["ssh:exec:read", "workspace:read"],
    }
    assert SubjectIdentity.from_dict(payload) == identity


def test_session_accessor_returns_the_published_token() -> None:
    token = TriadDelegationToken(
        initial_requester=_human("user_alice", "workspace:read"),
        executor_agent=_agent("agent_devops", "workspace:read"),
    )

    assert get_delegation_token() is None

    set_delegation_token(token)

    assert get_delegation_token() is token
