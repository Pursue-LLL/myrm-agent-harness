"""Unit tests for Pre-Flight Irreversible Write Interception and Emergency Kill Switch Suite."""

from __future__ import annotations

import time

import pytest

from myrm_agent_harness.core.security.irreversible_write_guard import (
    BlastRadiusBuilder,
    InterceptionStatus,
    IrreversibleWriteContract,
    IrreversibleWriteContractRegistry,
    PreFlightIrreversibleWriteGuard,
    RiskLevel,
    WriteDomain,
)


def test_contract_registry_defaults_and_custom() -> None:
    """Verify standard contract registry lookup, registration, and removal."""
    registry = IrreversibleWriteContractRegistry(load_defaults=True)
    assert registry.is_irreversible_write("send_email")
    assert registry.is_irreversible_write("git_push")
    assert registry.is_irreversible_write("stripe_charge")
    assert not registry.is_irreversible_write("read_file")

    # Custom contract
    custom = IrreversibleWriteContract(
        tool_name="aws_terminate_instance",
        domain=WriteDomain.DATABASE_WRITE,
        description="Terminate cloud VM instance",
        default_risk_level=RiskLevel.CRITICAL,
    )
    registry.register(custom)
    assert registry.is_irreversible_write("aws_terminate_instance")
    assert registry.find_contract("aws_terminate_instance") == custom

    # Unregister
    assert registry.unregister("aws_terminate_instance")
    assert not registry.is_irreversible_write("aws_terminate_instance")


def test_blast_radius_builder_domain_profiles() -> None:
    """Verify explosion radius card extraction across multiple domains."""
    # Email
    email_card = BlastRadiusBuilder.build_card(
        domain=WriteDomain.EMAIL,
        arguments={"to": "ceo@example.com", "subject": "Quarterly Report", "body": "Confidential data"},
    )
    assert email_card.domain == WriteDomain.EMAIL
    assert "ceo@example.com" in email_card.summary
    assert email_card.details["to"] == "ceo@example.com"
    assert email_card.risk_level == RiskLevel.HIGH

    # Git push with force push escalation
    git_card = BlastRadiusBuilder.build_card(
        domain=WriteDomain.GIT_PUSH,
        arguments={"remote": "origin", "branch": "main", "force": "true"},
    )
    assert git_card.domain == WriteDomain.GIT_PUSH
    assert git_card.risk_level == RiskLevel.CRITICAL
    assert git_card.details["force_push"] == "True"

    # Payment
    payment_card = BlastRadiusBuilder.build_card(
        domain=WriteDomain.PAYMENT,
        arguments={"amount": "5000", "currency": "USD", "recipient": "vendor_corp"},
    )
    assert payment_card.domain == WriteDomain.PAYMENT
    assert payment_card.risk_level == RiskLevel.CRITICAL
    assert payment_card.details["amount"] == "5000"


def test_guard_intercept_and_approve() -> None:
    """Verify interception of irreversible tools and subsequent user approval."""
    guard = PreFlightIrreversibleWriteGuard()

    # Safe tool is not intercepted
    assert guard.intercept("session_1", "read_file", {"path": "test.txt"}) is None

    # Irreversible tool is intercepted
    intent = guard.intercept(
        "session_1",
        "git_push",
        {"remote": "origin", "branch": "feat/login"},
    )
    assert intent is not None
    assert intent.status == InterceptionStatus.PENDING_CONFIRMATION
    assert intent.tool_name == "git_push"

    # Pending list should contain this intent
    pending = guard.list_pending("session_1")
    assert len(pending) == 1
    assert pending[0].intent_id == intent.intent_id

    # Approve
    approved = guard.approve(intent.intent_id, approver="security_admin")
    assert approved.status == InterceptionStatus.APPROVED
    assert "security_admin" in approved.resolution_reason

    # Pending list should now be empty
    assert len(guard.list_pending("session_1")) == 0

    # Cannot approve again
    with pytest.raises(ValueError, match="cannot be approved"):
        guard.approve(intent.intent_id)


def test_guard_emergency_kill_switch() -> None:
    """Verify emergency kill switch destroys payload and marks action aborted."""
    guard = PreFlightIrreversibleWriteGuard()

    intent = guard.intercept(
        "session_2",
        "stripe_charge",
        {"amount": "9999", "currency": "USD", "recipient": "attacker_wallet"},
    )
    assert intent is not None

    kill_res = guard.emergency_kill(intent.intent_id, reason="Malicious payment detected")
    assert kill_res.killed is True
    assert "Malicious payment detected" in kill_res.reason

    # Verify intent state
    stored = guard.get_intent(intent.intent_id)
    assert stored is not None
    assert stored.status == InterceptionStatus.KILLED_ABORTED
    assert stored.arguments == {}  # Payload zeroed out


def test_guard_ttl_expiration() -> None:
    """Verify that intents expire when TTL passes."""
    guard = PreFlightIrreversibleWriteGuard()

    # Intercept with 1-second TTL
    intent = guard.intercept(
        "session_3",
        "send_email",
        {"to": "partner@example.com", "subject": "Hi"},
        ttl_seconds=1,
    )
    assert intent is not None

    time.sleep(1.1)

    # Retrieval marks it timed out
    stored = guard.get_intent(intent.intent_id)
    assert stored is not None
    assert stored.status == InterceptionStatus.TIMED_OUT

    # Approval on expired intent fails
    with pytest.raises(ValueError, match="cannot be approved"):
        guard.approve(intent.intent_id)
