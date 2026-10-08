"""Unit tests for HeadlessCloudSandboxTaskContinuationAndMobileApprovalRelaySuite."""

from __future__ import annotations

import time
import pytest

from myrm_agent_harness.agent.context_management import (
    ApprovalDecisionKind,
    ClientAttachmentState,
    HeadlessContinuationSuite,
    HeadlessExecutionPhase,
    MobileApprovalDecisionPayload,
    MobileApprovalRelayEngine,
    RelayChannelKind,
    RiskLevel,
)


def test_mobile_approval_card_issuance_and_multichannel_render() -> None:
    """Test issuing HMAC-protected cards and rendering them across push channels."""
    engine = MobileApprovalRelayEngine(hmac_secret_key="unit-test-secret")

    card = engine.issue_relay_card(
        task_id="task-scan-001",
        session_id="sess-alpha-77",
        action_summary="Deploy production canary cluster",
        risk_level=RiskLevel.HIGH,
        ttl_seconds=600,
        channels=[RelayChannelKind.TELEGRAM, RelayChannelKind.WEBPUSH, RelayChannelKind.WECHAT_WORK],
        preview_meta={"cluster": "us-east-1", "replicas": "3"},
    )

    assert card.task_id == "task-scan-001"
    assert card.risk_level == RiskLevel.HIGH
    assert len(card.auth_token_digest) == 64
    assert card.payload_preview["cluster"] == "us-east-1"

    # Telegram payload
    tg_payload = engine.render_telegram_payload(card)
    assert tg_payload["channel"] == "telegram"
    assert "Approval Requested" in tg_payload["chat_text"]
    assert "Deploy production canary cluster" in tg_payload["chat_text"]

    # WebPush payload
    wp_payload = engine.render_webpush_payload(card)
    assert wp_payload["channel"] == "webpush"
    assert wp_payload["action_approve_id"] == "approve"

    # WeChat Work markdown
    wc_payload = engine.render_wechat_work_markdown(card)
    assert wc_payload["channel"] == "wechat_work"
    assert "沙箱脱机任务审批通知" in wc_payload["content"]


def test_mobile_approval_decision_resolution_and_tamper_defense() -> None:
    """Test valid callback, signature rejection, replay prevention, and expiration handling."""
    engine = MobileApprovalRelayEngine(hmac_secret_key="unit-test-secret")

    card = engine.issue_relay_card(
        task_id="task-002",
        session_id="sess-002",
        action_summary="Drop obsolete staging database",
        risk_level=RiskLevel.CRITICAL,
        ttl_seconds=300,
    )

    # 1. Invalid signature should raise PermissionError
    tampered_payload = MobileApprovalDecisionPayload(
        decision_id="dec-bad-01",
        request_id=card.request_id,
        decision=ApprovalDecisionKind.APPROVE,
        operator_id="admin-user-1",
        decision_reason="Looks good",
        signature_proof="tampered-fake-signature",
    )
    with pytest.raises(PermissionError):
        engine.resolve_decision(tampered_payload)

    # 2. Valid signature using card's matching token digest
    valid_payload = MobileApprovalDecisionPayload(
        decision_id="dec-ok-01",
        request_id=card.request_id,
        decision=ApprovalDecisionKind.APPROVE,
        operator_id="admin-user-1",
        decision_reason="Approved after mobile review",
        signature_proof=card.auth_token_digest,
    )
    receipt = engine.resolve_decision(valid_payload)
    assert receipt.decision == ApprovalDecisionKind.APPROVE
    assert receipt.is_expired is False
    assert receipt.operator_id == "admin-user-1"

    # 3. Replay of settled decision must raise ValueError
    with pytest.raises(ValueError):
        engine.resolve_decision(valid_payload)

    # 4. Expired card test
    expired_card = engine.issue_relay_card(
        task_id="task-003",
        session_id="sess-003",
        action_summary="Purge temporary logs",
        risk_level=RiskLevel.LOW,
        ttl_seconds=-10,  # Already expired
    )
    expired_payload = MobileApprovalDecisionPayload(
        decision_id="dec-exp-01",
        request_id=expired_card.request_id,
        decision=ApprovalDecisionKind.APPROVE,
        operator_id="admin-user-2",
        decision_reason="Late approval",
        signature_proof=expired_card.auth_token_digest,
    )
    exp_receipt = engine.resolve_decision(expired_payload)
    assert exp_receipt.is_expired is True
    assert "Expired" in exp_receipt.status_message


def test_headless_continuation_lifecycle_and_reconnection_sync() -> None:
    """Test full cycle: client detach -> headless run -> HITL suspend -> mobile approve -> reconnect."""
    suite = HeadlessContinuationSuite()
    task_id = "task-headless-longrun-99"
    session_id = "sess-longrun-99"

    suite.register_task(task_id, session_id)
    assert suite.get_client_state(task_id) == ClientAttachmentState.ATTACHED
    assert suite.get_execution_phase(task_id) == HeadlessExecutionPhase.IDLE

    # Client detaches (user closes desktop client)
    suite.notify_client_detach(task_id)
    assert suite.get_client_state(task_id) == ClientAttachmentState.DETACHED_HEADLESS
    assert suite.get_execution_phase(task_id) == HeadlessExecutionPhase.RUNNING_HEADLESS

    # Headless background progress
    suite.append_task_output(task_id, "Step 1: Downloading repository files...")
    suite.append_task_output(task_id, "Step 2: AST parsing completed with 0 errors.")

    # High-risk action triggers HITL suspension
    card = suite.suspend_for_approval(
        task_id=task_id,
        action_summary="Migrate schema on cloud database",
        risk_level=RiskLevel.HIGH,
    )
    assert suite.get_execution_phase(task_id) == HeadlessExecutionPhase.AWAITING_MOBILE_APPROVAL

    # Operator approves via mobile phone
    decision_payload = MobileApprovalDecisionPayload(
        decision_id="dec-mobile-42",
        request_id=card.request_id,
        decision=ApprovalDecisionKind.APPROVE,
        operator_id="operator-mobile-phone",
        decision_reason="Verified schema diff manually",
        signature_proof=card.auth_token_digest,
    )
    receipt = suite.resolve_mobile_approval(decision_payload)
    assert receipt.decision == ApprovalDecisionKind.APPROVE
    assert suite.get_execution_phase(task_id) == HeadlessExecutionPhase.RESUMED_ACTIVE

    # Execution completes in background
    suite.append_task_output(task_id, "Step 3: Database migration applied successfully.")
    suite.complete_task(task_id)
    assert suite.get_execution_phase(task_id) == HeadlessExecutionPhase.COMPLETED

    # User reopens desktop client: Reconnection sync manifest generated
    manifest = suite.generate_reconnection_manifest(task_id)
    assert manifest.task_id == task_id
    assert manifest.session_id == session_id
    assert manifest.execution_phase == HeadlessExecutionPhase.COMPLETED
    assert manifest.resume_ready is True
    assert manifest.approval_events_count == 1
    assert len(manifest.incremental_output_lines) == 3
    assert suite.get_client_state(task_id) == ClientAttachmentState.ATTACHED
