"""Unit tests for Native Credential Approvals and Precise Conversation Message Links.

[INPUT]
- Credential ask configurations, message sequence coordinates, and decision requests.

[OUTPUT]
- Verified behavior of link generation, authorization checks, and audit trails.

[POS]
- Harness unit test suite for QM #1502 native credential approval and session message linking.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.core.security.native_credential_approval import (
    ApprovalDecision,
    CredentialAskStatus,
    MessageLinkGenerator,
    NativeCredentialApprovalManager,
)


def test_message_link_generator_roundtrip_and_safety() -> None:
    generator = MessageLinkGenerator(base_route_prefix="/chat")

    link = generator.generate_link(
        session_id="session-xyz-123",
        message_id="msg-999",
        sequence_number=15,
    )
    assert link.path == "/chat/session-xyz-123"
    assert link.sequence_number == 15
    assert link.message_id == "msg-999"
    assert "seq=15" in link.deep_link_url
    assert "msg=msg-999" in link.deep_link_url

    # Roundtrip parsing
    parsed = generator.parse_link(link.deep_link_url)
    assert parsed is not None
    assert parsed.session_id == "session-xyz-123"
    assert parsed.message_id == "msg-999"
    assert parsed.sequence_number == 15

    # Path traversal and injection attacks are rejected
    with pytest.raises(ValueError, match="Invalid or unsafe session_id"):
        generator.generate_link(
            session_id="../../etc/passwd",
            message_id="msg-1",
            sequence_number=0,
        )

    with pytest.raises(ValueError, match="sequence_number must be non-negative"):
        generator.generate_link(
            session_id="sess-1",
            message_id="msg-1",
            sequence_number=-5,
        )


def test_create_and_list_pending_asks() -> None:
    manager = NativeCredentialApprovalManager()

    ask = manager.create_ask(
        credential_id="cred-github-pat",
        service_name="GitHub",
        account_label="octocat-corp",
        requester_id="code-reviewer-agent",
        owner_id="admin-user-01",
        purpose="Fetch private pull request diffs for analysis",
        session_id="sess-abc",
        message_id="msg-001",
        sequence_number=3,
    )

    assert ask.ask_id.startswith("ask-")
    assert ask.status == CredentialAskStatus.PENDING
    assert ask.service_name == "GitHub"
    assert ask.owner_id == "admin-user-01"
    assert ask.message_ref.sequence_number == 3
    assert ask.deep_link.deep_link_url == "/chat/sess-abc?seq=3&msg=msg-001"

    pending_all = manager.list_pending_asks()
    assert len(pending_all) == 1
    assert pending_all[0].ask_id == ask.ask_id

    pending_other = manager.list_pending_asks(owner_id="other-user")
    assert len(pending_other) == 0


def test_decide_ask_modes_and_audit() -> None:
    manager = NativeCredentialApprovalManager()

    ask_once = manager.create_ask(
        credential_id="cred-aws-s3",
        service_name="AWS",
        account_label="prod-read",
        requester_id="data-sync-agent",
        owner_id="devops-lead",
        purpose="Read deployment manifest",
        session_id="sess-deploy",
        message_id="msg-42",
        sequence_number=8,
    )

    # Approve with mode ONCE
    decided_once, audit_once = manager.decide_ask(
        ask_id=ask_once.ask_id,
        decider_id="devops-lead",
        decision=ApprovalDecision.ONCE,
        note="Approved for turn 8 only",
    )
    assert decided_once.status == CredentialAskStatus.APPROVED
    assert decided_once.decision_mode == ApprovalDecision.ONCE
    assert decided_once.decided_by == "devops-lead"
    assert decided_once.decision_note == "Approved for turn 8 only"

    assert audit_once.decision == ApprovalDecision.ONCE
    assert audit_once.actor_id == "devops-lead"
    assert audit_once.target_session_id == "sess-deploy"
    assert audit_once.sequence_number == 8

    # Approve another with mode STANDING
    ask_standing = manager.create_ask(
        credential_id="cred-postgres",
        service_name="Postgres",
        account_label="analytics-ro",
        requester_id="analyst-agent",
        owner_id="data-lead",
        purpose="Execute multi-query batch",
        session_id="sess-analytics",
        message_id="msg-100",
        sequence_number=1,
    )

    decided_standing, audit_standing = manager.decide_ask(
        ask_id=ask_standing.ask_id,
        decider_id="data-lead",
        decision=ApprovalDecision.STANDING,
        note="Session-wide read access approved",
    )
    assert decided_standing.status == CredentialAskStatus.APPROVED
    assert decided_standing.decision_mode == ApprovalDecision.STANDING
    assert audit_standing.decision == ApprovalDecision.STANDING
    assert audit_standing.actor_id == "data-lead"

    # Deny another ask
    ask_deny = manager.create_ask(
        credential_id="cred-root-ssh",
        service_name="SSH",
        account_label="bastion-root",
        requester_id="rogue-tool",
        owner_id="secops-lead",
        purpose="Interactive root shell",
        session_id="sess-suspect",
        message_id="msg-666",
        sequence_number=20,
    )
    decided_deny, audit_deny = manager.decide_ask(
        ask_id=ask_deny.ask_id,
        decider_id="secops-lead",
        decision=ApprovalDecision.DENY,
        note="Prohibited by root policy",
    )
    assert decided_deny.status == CredentialAskStatus.DENIED
    assert decided_deny.decision_mode == ApprovalDecision.DENY
    assert audit_deny.decision == ApprovalDecision.DENY


def test_authorization_checks_and_state_guards() -> None:
    manager = NativeCredentialApprovalManager()

    ask = manager.create_ask(
        credential_id="cred-stripe",
        service_name="Stripe",
        account_label="live-charge",
        requester_id="billing-agent",
        owner_id="finance-director",
        purpose="Refund transaction",
        session_id="sess-billing",
        message_id="msg-99",
        sequence_number=4,
    )

    # Impersonator attempting decision is rejected
    with pytest.raises(PermissionError, match="Only the credential owner can decide"):
        manager.decide_ask(
            ask_id=ask.ask_id,
            decider_id="unauthorized-intruder",
            decision=ApprovalDecision.ONCE,
        )

    # Legitimate owner approves
    manager.decide_ask(
        ask_id=ask.ask_id,
        decider_id="finance-director",
        decision=ApprovalDecision.ONCE,
    )

    # Cannot decide again after already decided
    with pytest.raises(ValueError, match=r"Cannot decide ask .* with status 'approved'"):
        manager.decide_ask(
            ask_id=ask.ask_id,
            decider_id="finance-director",
            decision=ApprovalDecision.DENY,
        )
