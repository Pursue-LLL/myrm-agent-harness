"""
Unit tests for Bot Screen Auditable Operational Control & Intervention Evidence Suite.
"""

from __future__ import annotations

from myrm_agent_harness.core.security.bot_screen_intervention import (
    ApprovalDecision,
    BotScreenAssertionProbeRunner,
    BotScreenAuditableControlSuite,
    BotScreenInterventionEvidenceRecorder,
    BotScreenOperationalBoundaryGuard,
    ScreenElementAction,
    ScreenRiskTier,
)


def test_operational_boundary_guard_classification_and_decisions() -> None:
    guard = BotScreenOperationalBoundaryGuard()

    # 1. High-risk financial ERP interaction
    tier_fin = guard.classify_element_risk(
        selector="#btn-confirm-wire-transfer",
        label="Confirm Wire Transfer",
        action_type="click",
    )
    assert tier_fin == ScreenRiskTier.HIGH_RISK_FINANCIAL

    act_fin = ScreenElementAction(
        action_id="act-1",
        target_selector="#btn-confirm-wire-transfer",
        action_type="click",
        label="Confirm Wire Transfer",
        value_masked="",
        risk_tier=tier_fin,
    )
    dec_fin, reason_fin = guard.evaluate_action_boundary(act_fin)
    assert dec_fin == ApprovalDecision.PENDING_HUMAN_APPROVAL
    assert "checkpoint approval" in reason_fin

    # 2. Critical admin destructive action
    tier_crit = guard.classify_element_risk(
        selector="#purge-database-records",
        label="Purge Production Database",
        action_type="click",
    )
    assert tier_crit == ScreenRiskTier.CRITICAL_ADMIN

    act_crit = ScreenElementAction(
        action_id="act-2",
        target_selector="#purge-database-records",
        action_type="click",
        label="Purge Production Database",
        value_masked="",
        risk_tier=tier_crit,
    )
    dec_crit, reason_crit = guard.evaluate_action_boundary(act_crit)
    assert dec_crit == ApprovalDecision.MANUAL_TAKEOVER_REQUIRED
    assert "takeover" in reason_crit

    # 3. Standard write action
    tier_write = guard.classify_element_risk(
        selector="#input-order-notes",
        label="Order Notes",
        action_type="type",
    )
    assert tier_write == ScreenRiskTier.STANDARD_WRITE
    act_write = ScreenElementAction(
        action_id="act-3",
        target_selector="#input-order-notes",
        action_type="type",
        label="Order Notes",
        value_masked="Expedite delivery",
        risk_tier=tier_write,
    )
    dec_write, _ = guard.evaluate_action_boundary(act_write)
    assert dec_write == ApprovalDecision.APPROVED_AUTOMATIC

    # 4. Safe read-only action
    tier_read = guard.classify_element_risk(
        selector="#scroll-container",
        label="Audit Log View",
        action_type="scroll",
    )
    assert tier_read == ScreenRiskTier.SAFE_READONLY


def test_intervention_evidence_recorder_lifecycle_and_tamper_evidence() -> None:
    recorder = BotScreenInterventionEvidenceRecorder()

    # 1. Begin human intervention
    session_id = "session-erp-001"
    operator_id = "compliance_officer_9"
    before_hash = "sha256_before_aaa111"

    intervene_id = recorder.start_intervention(session_id, operator_id, before_hash)
    assert intervene_id.startswith("intervene-")

    # 2. Record keystroke/mouse events with credential scrubbing
    evt1 = recorder.record_event(
        intervention_id=intervene_id,
        event_type="mouse_click",
        target_selector="#btn-edit-bank-details",
        raw_data="clicked coordinates (420, 180)",
    )
    assert evt1 is not None
    assert evt1.data_sanitized == "clicked coordinates (420, 180)"

    # Password input must be redacted
    evt2 = recorder.record_event(
        intervention_id=intervene_id,
        event_type="keyboard_input",
        target_selector="#input-admin-password",
        raw_data="super_secret_master_password",
    )
    assert evt2 is not None
    assert evt2.data_sanitized == "[REDACTED_SENSITIVE_CREDENTIAL]"

    # 3. Seal evidence bundle
    after_hash = "sha256_after_bbb222"
    bundle = recorder.seal_evidence_bundle(intervene_id, after_hash)
    assert bundle is not None
    assert bundle.session_id == session_id
    assert bundle.operator_id == operator_id
    assert bundle.before_snapshot_hash == before_hash
    assert bundle.after_snapshot_hash == after_hash
    assert bundle.event_count == 2
    assert bundle.is_tamper_evident
    assert len(bundle.bundle_sha256) == 64

    # 4. Bundle query
    queried = recorder.get_bundle(intervene_id)
    assert queried == bundle

    # 5. Invalid calls gracefully return None
    assert recorder.record_event("invalid-id", "click", "#btn", "data") is None
    assert recorder.seal_evidence_bundle("invalid-id", "after_hash") is None


def test_autonomous_assertion_probe_runner() -> None:
    runner = BotScreenAssertionProbeRunner()

    # Success case: text present and visual match
    p1 = runner.verify_screen_assertion(
        probe_id="probe-success-1",
        expected_selector="#toast-notification",
        expected_text_contains="Transfer successful",
        actual_text="Payment of $500 executed. Transfer successful.",
        visual_hash_match=True,
    )
    assert p1.passed
    assert "asserted successfully" in p1.detail

    # Failure case 1: text absent
    p2 = runner.verify_screen_assertion(
        probe_id="probe-fail-text",
        expected_selector="#toast-notification",
        expected_text_contains="Approved",
        actual_text="An internal error occurred.",
        visual_hash_match=True,
    )
    assert not p2.passed
    assert "not found" in p2.detail

    # Failure case 2: visual layout mismatch
    p3 = runner.verify_screen_assertion(
        probe_id="probe-fail-visual",
        expected_selector="#table-rows",
        expected_text_contains="Row 1",
        actual_text="Table with Row 1 loaded",
        visual_hash_match=False,
    )
    assert not p3.passed
    assert "Visual snapshot hash diverged" in p3.detail


def test_bot_screen_intervention_facade_and_metrics() -> None:
    suite = BotScreenAuditableControlSuite()

    # 1. Evaluate actions and verify metrics
    act1 = ScreenElementAction(
        action_id="act-wire",
        target_selector="#btn-wire-payout",
        action_type="click",
        label="Disburse Vendor Payment",
        value_masked="",
        risk_tier=ScreenRiskTier.HIGH_RISK_FINANCIAL,
    )
    dec1, _ = suite.evaluate_action(act1)
    assert dec1 == ApprovalDecision.PENDING_HUMAN_APPROVAL

    act2 = ScreenElementAction(
        action_id="act-delete",
        target_selector="#btn-purge-table",
        action_type="click",
        label="Purge Production Records",
        value_masked="",
        risk_tier=ScreenRiskTier.CRITICAL_ADMIN,
    )
    dec2, _ = suite.evaluate_action(act2)
    assert dec2 == ApprovalDecision.MANUAL_TAKEOVER_REQUIRED

    # 2. Human intervention lifecycle
    intervene_id = suite.start_intervention("session-99", "admin_alice", "hash_before_123")
    evt = suite.record_intervention_event(intervene_id, "mouse_click", "#input-pwd", "secret123")
    assert evt is not None
    assert evt.data_sanitized == "[REDACTED_SENSITIVE_CREDENTIAL]"

    bundle = suite.seal_intervention_bundle(intervene_id, "hash_after_456")
    assert bundle is not None
    assert suite.get_evidence_bundle(intervene_id) is not None

    # 3. Autonomous assertion probe failure count
    probe_fail = suite.verify_screen_assertion(
        probe_id="probe-fail",
        expected_selector="#status",
        expected_text_contains="Done",
        actual_text="Processing...",
        visual_hash_match=True,
    )
    assert not probe_fail.passed

    # 4. Verify metrics accumulation
    metrics = suite.metrics
    assert metrics.total_screen_actions == 2
    assert metrics.approval_checkpoints_triggered == 1
    assert metrics.manual_takeovers_conducted == 1
    assert metrics.evidence_bundles_sealed == 1
    assert metrics.assertion_failures == 1
