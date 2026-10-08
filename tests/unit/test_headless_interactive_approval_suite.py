"""Unit tests for Headless Agent Interactive Approval, Webhook Relay, and Hold-Resume Suite."""

from __future__ import annotations

import asyncio

import pytest

from myrm_agent_harness.core.security.headless_interactive_approval import (
    ApprovalHoldStatus,
    HeadlessHoldStateMachine,
    InteractiveApprovalWebhookRelay,
    RiskActionDescriptor,
    StreamingContinuationConduit,
)


@pytest.mark.asyncio
async def test_hold_state_machine_approval_flow() -> None:
    sm = HeadlessHoldStateMachine(base_approval_url="https://secops.corp/approve")
    action = RiskActionDescriptor(
        action_id="act_rm_rf",
        tool_name="bash",
        command_or_target="rm -rf /tmp/staging_cache",
        risk_level="CRITICAL",
        justification="Clean up temporary files",
    )

    # 1. Create ticket
    ticket = sm.create_hold_ticket(
        session_id="session_headless_01",
        action=action,
        timeout_seconds=5.0,
    )
    assert ticket.tx_id.startswith("tx-")
    assert ticket.status == ApprovalHoldStatus.PENDING
    assert ticket.shortlink_url.startswith("https://secops.corp/approve?tx=")

    # 2. Concurrently wait and approve
    async def delayed_approve() -> None:
        await asyncio.sleep(0.05)
        sm.submit_decision(
            tx_id=ticket.tx_id,
            decision=ApprovalHoldStatus.APPROVED,
            operator="secops_lead",
            notes="Authorized for cache cleanup only.",
        )

    approve_task = asyncio.create_task(delayed_approve())
    resolved = await sm.wait_for_decision(ticket.tx_id, timeout_seconds=2.0)
    await approve_task

    assert resolved.status == ApprovalHoldStatus.APPROVED
    assert resolved.decided_by == "secops_lead"
    assert resolved.operator_decision_notes == "Authorized for cache cleanup only."


@pytest.mark.asyncio
async def test_hold_state_machine_rejection_and_timeout() -> None:
    sm = HeadlessHoldStateMachine()
    action = RiskActionDescriptor(
        action_id="act_drop_table",
        tool_name="database_repl",
        command_or_target="DROP TABLE customers CASCADE;",
        risk_level="CRITICAL",
        justification="Reset database table",
    )

    # 1. Rejection
    ticket_rej = sm.create_hold_ticket(
        session_id="session_headless_02",
        action=action,
        timeout_seconds=10.0,
    )
    sm.submit_decision(
        tx_id=ticket_rej.tx_id,
        decision=ApprovalHoldStatus.REJECTED,
        operator="dba_admin",
        notes="Dangerous destructive statement rejected.",
    )
    resolved_rej = await sm.wait_for_decision(ticket_rej.tx_id)
    assert resolved_rej.status == ApprovalHoldStatus.REJECTED
    assert resolved_rej.decided_by == "dba_admin"

    # 2. Timeout
    ticket_timeout = sm.create_hold_ticket(
        session_id="session_headless_03",
        action=action,
        timeout_seconds=0.05,  # Very short timeout
    )
    await asyncio.sleep(0.06)
    resolved_timeout = sm.get_ticket(ticket_timeout.tx_id)
    assert resolved_timeout is not None
    assert resolved_timeout.status == ApprovalHoldStatus.TIMED_OUT


def test_webhook_relay_and_markdown_card() -> None:
    relay = InteractiveApprovalWebhookRelay()
    relay.register_endpoint("telegram_alert", "https://api.telegram.org/bot/notify")
    relay.register_endpoint("feishu_webhook", "https://open.feishu.cn/open-apis/bot/v2/hook/...")

    endpoints = relay.list_endpoints()
    assert len(endpoints) == 2
    assert "telegram_alert" in endpoints

    # Create dummy ticket
    action = RiskActionDescriptor(
        action_id="act_01",
        tool_name="file_writer",
        command_or_target="/etc/systemd/service.conf",
        risk_level="HIGH",
        justification="Update daemon config",
    )
    sm = HeadlessHoldStateMachine()
    ticket = sm.create_hold_ticket(session_id="sess_wb", action=action)

    payload = relay.build_payload(ticket, custom_metadata={"cluster": "us-east-1"})
    assert payload.tx_id == ticket.tx_id
    assert payload.tool_name == "file_writer"
    assert payload.custom_metadata["cluster"] == "us-east-1"

    card = relay.format_markdown_card(ticket)
    assert ticket.tx_id in card
    assert "file_writer" in card
    assert ticket.shortlink_url in card


def test_streaming_continuation_conduit_notices() -> None:
    conduit = StreamingContinuationConduit()
    action = RiskActionDescriptor(
        action_id="act_02",
        tool_name="aws_cli",
        command_or_target="aws s3 rm s3://bucket --recursive",
        risk_level="CRITICAL",
        justification="Purge bucket",
    )
    sm = HeadlessHoldStateMachine()
    ticket = sm.create_hold_ticket(session_id="sess_stream", action=action)

    # 1. Hold notice
    chunk_hold = conduit.format_hold_reasoning_block(ticket)
    assert chunk_hold.is_resumed is False
    assert "安全挂起" in chunk_hold.inject_markdown
    assert ticket.shortlink_url in chunk_hold.inject_markdown

    # 2. Approved notice
    sm.submit_decision(ticket.tx_id, ApprovalHoldStatus.APPROVED, "operator_bob")
    approved_ticket = sm.get_ticket(ticket.tx_id)
    assert approved_ticket is not None
    chunk_approved = conduit.format_resumed_reasoning_block(approved_ticket)
    assert chunk_approved.is_resumed is True
    assert "审批已通过" in chunk_approved.inject_markdown
    assert "operator_bob" in chunk_approved.inject_markdown

    # 3. Rejected notice
    ticket_rejected = sm.create_hold_ticket(session_id="sess_rej", action=action)
    sm.submit_decision(ticket_rejected.tx_id, ApprovalHoldStatus.REJECTED, "operator_eve", "High risk")
    t_rej = sm.get_ticket(ticket_rejected.tx_id)
    assert t_rej is not None
    chunk_rejected = conduit.format_resumed_reasoning_block(t_rej)
    assert "审批已拒绝" in chunk_rejected.inject_markdown
    assert "operator_eve" in chunk_rejected.inject_markdown
