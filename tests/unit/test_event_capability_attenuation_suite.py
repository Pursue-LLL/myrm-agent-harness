"""
[POS] tests/unit/test_event_capability_attenuation_suite.py
[INPUT] myrm_agent_harness.core.security.event_capability_attenuation
[OUTPUT] Unit test suite for Event-Triggered Capability Attenuation & Async Approval Bridge

Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import time

from myrm_agent_harness.core.security.event_capability_attenuation import (
    ApprovalTicketStatusEnum,
    AsyncApprovalBridge,
    CapabilityAttenuationCapsule,
    ChannelNotificationTarget,
    EventCapabilityAttenuationFacade,
    EventSignatureVerifier,
    EventTrustScopeEnum,
    TicketRiskLevelEnum,
)


def test_event_signature_verification() -> None:
    """Test HMAC-SHA256 verification of event payloads."""
    verifier = EventSignatureVerifier()
    source = "github_webhook"
    secret = "secret_key_12345"
    payload = b'{"action": "issue_comment", "comment": "deploy now"}'

    verifier.register_source_secret(source, secret)
    valid_sig = verifier.compute_signature(source, payload)

    # 1. Valid signature
    desc_valid = verifier.verify_event(
        event_id="evt-001",
        source_name=source,
        event_type="webhook",
        timestamp=time.time(),
        raw_payload_bytes=payload,
        signature=valid_sig,
    )
    assert desc_valid.is_verified is True
    assert desc_valid.event_id == "evt-001"

    # 2. Tampered signature
    desc_tampered = verifier.verify_event(
        event_id="evt-002",
        source_name=source,
        event_type="webhook",
        timestamp=time.time(),
        raw_payload_bytes=payload,
        signature="invalid_hex_signature",
    )
    assert desc_tampered.is_verified is False

    # 3. Unregistered source
    desc_unknown = verifier.verify_event(
        event_id="evt-003",
        source_name="unregistered_mcp",
        event_type="event",
        timestamp=time.time(),
        raw_payload_bytes=payload,
        signature="any_sig",
    )
    assert desc_unknown.is_verified is False


def test_capability_attenuation_capsule_scopes() -> None:
    """Test tool permission boundaries across interactive, low-trust, and quarantine scopes."""
    capsule = CapabilityAttenuationCapsule()
    sess_interactive = "sess-user-01"
    sess_event = "sess-event-01"
    sess_quarantine = "sess-quarantine-01"

    capsule.set_session_scope(sess_interactive, EventTrustScopeEnum.USER_INTERACTIVE)
    capsule.set_session_scope(sess_event, EventTrustScopeEnum.LOW_TRUST_EVENT_SCOPE)
    capsule.set_session_scope(sess_quarantine, EventTrustScopeEnum.ISOLATED_QUARANTINE)

    # 1. User interactive: full execution allowed
    allowed_u, _, risk_u = capsule.evaluate_tool_access(sess_interactive, "rm_rf")
    assert allowed_u is True
    assert risk_u == TicketRiskLevelEnum.LOW

    # 2. Low-trust event scope: read-only safe tools pass
    allowed_r, _, _ = capsule.evaluate_tool_access(sess_event, "file_read")
    assert allowed_r is True

    # Low-trust event scope: blocked destructive tools require approval
    allowed_b, reason_b, risk_b = capsule.evaluate_tool_access(sess_event, "shell_exec")
    assert allowed_b is False
    assert "attenuated under external event scope" in reason_b
    assert risk_b in (TicketRiskLevelEnum.HIGH, TicketRiskLevelEnum.CRITICAL)

    # Low-trust event scope: uncategorized write tool requires approval
    allowed_w, _, risk_w = capsule.evaluate_tool_access(sess_event, "custom_writer")
    assert allowed_w is False
    assert risk_w == TicketRiskLevelEnum.MEDIUM

    # 3. Quarantine scope: only read-only allowed
    allowed_q_ro, _, _ = capsule.evaluate_tool_access(sess_quarantine, "file_read")
    assert allowed_q_ro is True
    allowed_q_bl, _, risk_q = capsule.evaluate_tool_access(sess_quarantine, "custom_writer")
    assert allowed_q_bl is False
    assert risk_q == TicketRiskLevelEnum.CRITICAL


def test_async_approval_bridge_ticket_lifecycle() -> None:
    """Test approval ticket creation, approval token granting, rejection, and expiry."""
    bridge = AsyncApprovalBridge(default_ttl_seconds=10.0)
    channel = ChannelNotificationTarget(channel_type="feishu", target_id="chat-dept-01")

    # 1. Create ticket
    ticket = bridge.create_ticket(
        session_id="sess-001",
        requested_tool="git_push",
        risk_level=TicketRiskLevelEnum.HIGH,
        action_description="Push automated hotfix to repository",
        diff_payload="+ fixed bug in auth module",
        channels=[channel],
    )
    assert ticket.status == ApprovalTicketStatusEnum.PENDING
    assert len(ticket.notification_channels) == 1

    # 2. Approve ticket and obtain single-use token
    approved_ticket, grant_token = bridge.approve_ticket(
        ticket.ticket_id,
        decided_by="lead_engineer_alice",
        decision_reason="LGTM",
    )
    assert approved_ticket is not None
    assert approved_ticket.status == ApprovalTicketStatusEnum.APPROVED
    assert approved_ticket.decided_by == "lead_engineer_alice"
    assert grant_token is not None

    # 3. Consume token
    matched_id = bridge.consume_one_time_token(grant_token)
    assert matched_id == ticket.ticket_id
    # Replay consumption fails
    assert bridge.consume_one_time_token(grant_token) is None

    # 4. Reject ticket
    ticket_rej = bridge.create_ticket(
        session_id="sess-002",
        requested_tool="drop_database",
        risk_level=TicketRiskLevelEnum.CRITICAL,
        action_description="Drop stale test db",
        diff_payload="",
    )
    rejected = bridge.reject_ticket(ticket_rej.ticket_id, decided_by="admin_bob", decision_reason="Prohibited")
    assert rejected is not None
    assert rejected.status == ApprovalTicketStatusEnum.REJECTED

    # 5. Expiration evaluation
    ticket_exp = bridge.create_ticket(
        session_id="sess-003",
        requested_tool="shell_exec",
        risk_level=TicketRiskLevelEnum.HIGH,
        action_description="Execute batch script",
        diff_payload="",
        custom_ttl_seconds=0.01,
    )
    # Check expiry after future timestamp
    t_retrieved = bridge.get_ticket(ticket_exp.ticket_id, current_time=time.time() + 100)
    assert t_retrieved is not None
    assert t_retrieved.status == ApprovalTicketStatusEnum.EXPIRED


def test_facade_end_to_end_and_metrics() -> None:
    """Test facade coordinated event ingestion, scope binding, ticket creation and metric updates."""
    facade = EventCapabilityAttenuationFacade()
    source = "mcp_events_server"
    secret = "secret_mcp_xyz"
    facade.register_event_secret(source, secret)

    payload = b'{"trigger": "nightly_ci_failure", "repo": "open-perplexity"}'
    from myrm_agent_harness.core.security.event_capability_attenuation import EventSignatureVerifier

    sig = EventSignatureVerifier()
    sig.register_source_secret(source, secret)
    signature = sig.compute_signature(source, payload)

    # Ingest event with auto session binding
    session_id = "sess-nightly-001"
    desc = facade.verify_and_ingest_event(
        event_id="evt-ci-01",
        source_name=source,
        event_type="ci_event",
        timestamp=time.time(),
        raw_payload_bytes=payload,
        signature=signature,
        auto_bind_session_id=session_id,
    )
    assert desc.is_verified is True
    assert facade.get_session_scope(session_id) == EventTrustScopeEnum.LOW_TRUST_EVENT_SCOPE

    # Evaluate tool
    allowed, _, risk = facade.evaluate_tool(session_id, "deploy_production")
    assert allowed is False

    # Create ticket
    ticket = facade.create_approval_ticket(
        session_id=session_id,
        requested_tool="deploy_production",
        risk_level=risk,
        action_description="Deploy hotfix after CI repair",
        diff_payload="diff --git a/app.py b/app.py",
    )
    assert len(facade.list_pending_tickets()) == 1

    # Approve and consume
    app_tkt, tok = facade.approve_ticket(ticket.ticket_id, decided_by="devops_oncall")
    assert app_tkt is not None and tok is not None
    assert facade.verify_and_consume_token(tok) == ticket.ticket_id

    # Metrics
    metrics = facade.get_metrics()
    assert metrics.total_events_received == 1
    assert metrics.verified_events_count == 1
    assert metrics.attenuated_executions_count == 1
    assert metrics.tickets_created == 1
    assert metrics.tickets_approved == 1
