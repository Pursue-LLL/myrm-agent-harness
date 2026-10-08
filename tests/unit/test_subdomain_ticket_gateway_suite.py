"""
Unit tests for Short-Lived Ticket Session Exchange & Subdomain Isolated Gateway Suite.
"""

from __future__ import annotations

import time

from myrm_agent_harness.core.security.subdomain_ticket_gateway import (
    AirgapAccessVerdict,
    ShortLivedTicketExchangeManager,
    SubdomainAirgapGuard,
    SubdomainIsolatedGatewaySuite,
    TicketValidationStatus,
)


def test_ticket_exchange_manager_lifecycle_and_security() -> None:
    manager = ShortLivedTicketExchangeManager(ticket_ttl_seconds=0.1)

    # 1. Normal issue and successful redemption
    ticket = manager.issue_ticket(
        master_user_id="user-corp-88",
        target_instance_id="sandbox-inst-01",
        client_ip="192.168.1.10",
        client_fingerprint="fp-browser-hash-xyz",
    )
    assert ticket.ticket_id.startswith("tkt-")
    assert not ticket.is_consumed

    status, session = manager.redeem_ticket(
        ticket_id=ticket.ticket_id,
        client_ip="192.168.1.10",
        client_fingerprint="fp-browser-hash-xyz",
    )
    assert status == TicketValidationStatus.VALID
    assert session is not None
    assert session.instance_id == "sandbox-inst-01"
    assert session.user_id == "user-corp-88"

    # 2. Anti-replay prevention: Re-redeeming consumed ticket must be blocked
    status_replay, session_replay = manager.redeem_ticket(
        ticket_id=ticket.ticket_id,
        client_ip="192.168.1.10",
        client_fingerprint="fp-browser-hash-xyz",
    )
    assert status_replay == TicketValidationStatus.ALREADY_CONSUMED
    assert session_replay is None

    # 3. Client IP / fingerprint mismatch prevention
    ticket2 = manager.issue_ticket(
        master_user_id="user-corp-88",
        target_instance_id="sandbox-inst-01",
        client_ip="192.168.1.10",
        client_fingerprint="fp-browser-hash-xyz",
    )
    status_mismatch, _ = manager.redeem_ticket(
        ticket_id=ticket2.ticket_id,
        client_ip="10.0.0.99",  # Spoofed IP
        client_fingerprint="fp-browser-hash-xyz",
    )
    assert status_mismatch == TicketValidationStatus.FINGERPRINT_MISMATCH

    # 4. TTL expiration
    ticket_exp = manager.issue_ticket(
        master_user_id="user-corp-88",
        target_instance_id="sandbox-inst-01",
        client_ip="192.168.1.10",
        client_fingerprint="fp-browser-hash-xyz",
    )
    time.sleep(0.12)  # Wait for 0.1s TTL to expire
    status_exp, _ = manager.redeem_ticket(
        ticket_id=ticket_exp.ticket_id,
        client_ip="192.168.1.10",
        client_fingerprint="fp-browser-hash-xyz",
    )
    assert status_exp == TicketValidationStatus.EXPIRED

    # 5. Session validation and revocation
    assert manager.validate_instance_session(session.session_id, "sandbox-inst-01")
    assert not manager.validate_instance_session(session.session_id, "sandbox-inst-other")
    assert manager.revoke_session(session.session_id)
    assert not manager.validate_instance_session(session.session_id, "sandbox-inst-01")


def test_subdomain_airgap_guard_rules() -> None:
    guard = SubdomainAirgapGuard()

    # 1. Block master control plane uplink attempt
    res_admin = guard.evaluate_egress_request(
        current_instance_id="sandbox-inst-01",
        requested_path="/api/v1/admin/cluster/nodes",
    )
    assert not res_admin.is_allowed
    assert res_admin.verdict == AirgapAccessVerdict.BLOCKED_MASTER_CONTROL_PLANE_ATTEMPT

    res_org = guard.evaluate_egress_request(
        current_instance_id="sandbox-inst-01",
        requested_path="/api/v1/organizations/billing",
    )
    assert not res_org.is_allowed
    assert res_org.verdict == AirgapAccessVerdict.BLOCKED_MASTER_CONTROL_PLANE_ATTEMPT

    # 2. Block cross-instance lateral traversal attempt
    res_cross = guard.evaluate_egress_request(
        current_instance_id="sandbox-inst-01",
        requested_path="/api/v1/tools/execute",
        target_instance_id="sandbox-inst-other-tenant",
    )
    assert not res_cross.is_allowed
    assert res_cross.verdict == AirgapAccessVerdict.BLOCKED_CROSS_INSTANCE_ATTEMPT

    # 3. Allow legitimate local sandbox execution calls
    res_local = guard.evaluate_egress_request(
        current_instance_id="sandbox-inst-01",
        requested_path="/api/v1/tools/run-python",
        target_instance_id="sandbox-inst-01",
    )
    assert res_local.is_allowed
    assert res_local.verdict == AirgapAccessVerdict.ALLOWED_SANDBOX_LOCAL


def test_subdomain_isolated_gateway_facade_and_metrics() -> None:
    suite = SubdomainIsolatedGatewaySuite()

    # Issue ticket
    tkt = suite.issue_exchange_ticket(
        master_user_id="user-1",
        target_instance_id="inst-1",
        client_ip="127.0.0.1",
        client_fingerprint="fp-test",
    )
    assert suite.metrics.tickets_issued_total == 1

    # Redeem ticket
    status, sess = suite.redeem_exchange_ticket(
        ticket_id=tkt.ticket_id,
        client_ip="127.0.0.1",
        client_fingerprint="fp-test",
    )
    assert status == TicketValidationStatus.VALID
    assert sess is not None
    assert suite.metrics.tickets_redeemed_total == 1
    assert suite.metrics.active_sessions_total == 1

    # Replay attempt
    suite.redeem_exchange_ticket(
        ticket_id=tkt.ticket_id,
        client_ip="127.0.0.1",
        client_fingerprint="fp-test",
    )
    assert suite.metrics.replay_attacks_blocked_total == 1

    # Validate & Revoke session
    assert suite.validate_instance_session(sess.session_id, "inst-1")
    assert suite.revoke_session(sess.session_id)
    assert suite.metrics.active_sessions_total == 0

    # Airgap check via facade
    airgap_res = suite.evaluate_airgap_request(
        current_instance_id="inst-1",
        requested_path="/api/v1/admin/secrets",
    )
    assert not airgap_res.is_allowed
    assert suite.metrics.airgap_violations_blocked_total == 1
