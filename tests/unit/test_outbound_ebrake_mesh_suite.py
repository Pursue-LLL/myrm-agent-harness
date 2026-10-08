"""
[POS] tests/unit/test_outbound_ebrake_mesh_suite.py
[INPUT] myrm_agent_harness.core.security.outbound_ebrake_mesh
[OUTPUT] Unit tests for Outbound Irreversible Action E-Brake & Privacy-Preserving Chief of Staff Mesh Suite

Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import time

from myrm_agent_harness.core.security.outbound_ebrake_mesh import (
    ActionBufferStatus,
    AudienceRiskTier,
    CalendarNegotiationResult,
    CalendarTimeSlot,
    EBrakeStatus,
    GhostInspectionVerdict,
    OutboundActionItem,
    OutboundActionType,
    OutboundEBrakeAndChiefOfStaffMeshFacade,
)


def test_ghost_inspection_domain_and_secret_redaction() -> None:
    """Test pre-flight ghost inspection detecting external domains and credential exfiltration."""
    facade = OutboundEBrakeAndChiefOfStaffMeshFacade()

    # 1. Internal destination with safe payload
    v1: GhostInspectionVerdict = facade.inspect_outbound_action(
        action_type=OutboundActionType.EMAIL_DISPATCH,
        destination_target="alice@corp.internal",
        payload_text="Here is the quarterly budget summary.",
    )
    assert v1.is_safe_to_queue is True
    assert v1.risk_tier == AudienceRiskTier.INTERNAL_SAFE
    assert len(v1.tainted_tokens_detected) == 0

    # 2. Trusted external destination with clean text
    v2: GhostInspectionVerdict = facade.inspect_outbound_action(
        action_type=OutboundActionType.WEBHOOK_CALL,
        destination_target="https://api.github.com/repos/org/repo/dispatches",
        payload_text="Trigger build workflow run #104",
    )
    assert v2.is_safe_to_queue is True
    assert v2.risk_tier == AudienceRiskTier.EXTERNAL_TRUSTED

    # 3. Untrusted external destination without secrets (safe to queue but marked untrusted)
    v3: GhostInspectionVerdict = facade.inspect_outbound_action(
        action_type=OutboundActionType.EMAIL_DISPATCH,
        destination_target="partner@external-client.org",
        payload_text="Sharing non-sensitive meeting notes.",
    )
    assert v3.is_safe_to_queue is True
    assert v3.risk_tier == AudienceRiskTier.EXTERNAL_UNTRUSTED

    # 4. Exfiltration attempt: API key sent to untrusted external recipient (prohibited leak)
    v4: GhostInspectionVerdict = facade.inspect_outbound_action(
        action_type=OutboundActionType.EMAIL_DISPATCH,
        destination_target="stranger@gmail.com",
        payload_text="Here is my API token: sk-abcdef123456789012345678 for access.",
    )
    assert v4.is_safe_to_queue is False
    assert v4.risk_tier == AudienceRiskTier.PROHIBITED_LEAK
    assert "OPENAI_KEY" in v4.tainted_tokens_detected
    assert "Blocked exfiltration" in v4.ghost_summary


def test_grace_period_buffer_lifecycle() -> None:
    """Test queueing, cancellation, and manual flush in grace period buffer."""
    facade = OutboundEBrakeAndChiefOfStaffMeshFacade()

    # 1. Enqueue an action
    item1: OutboundActionItem = facade.enqueue_action(
        task_id="task-email-01",
        action_type=OutboundActionType.EMAIL_DISPATCH,
        destination_target="team@corp.internal",
        payload_text="Project milestone reached.",
        risk_tier=AudienceRiskTier.INTERNAL_SAFE,
        grace_period_seconds=10.0,
    )
    assert item1.status == ActionBufferStatus.QUEUED_IN_GRACE_PERIOD
    assert item1.action_id.startswith("act-")

    # 2. Manual cancel during grace period
    cancelled = facade.cancel_action(item1.action_id, reason="User clicked cancel")
    assert cancelled is True

    fetched1 = facade.get_action(item1.action_id)
    assert fetched1 is not None
    assert fetched1.status == ActionBufferStatus.CANCELLED_BY_USER
    assert fetched1.cancellation_reason == "User clicked cancel"

    # 3. Enqueue second item and flush immediately
    item2: OutboundActionItem = facade.enqueue_action(
        task_id="task-webhook-02",
        action_type=OutboundActionType.WEBHOOK_CALL,
        destination_target="https://slack.com/api/chat.postMessage",
        payload_text="Deployment completed successfully.",
        risk_tier=AudienceRiskTier.EXTERNAL_TRUSTED,
        grace_period_seconds=10.0,
    )
    flushed = facade.flush_action(item2.action_id)
    assert flushed is True

    fetched2 = facade.get_action(item2.action_id)
    assert fetched2 is not None
    assert fetched2.status == ActionBufferStatus.DISPATCHED_AFTER_GRACE


def test_grace_period_timeout_dispatch() -> None:
    """Test automatic dispatch after grace timeout elapses."""
    facade = OutboundEBrakeAndChiefOfStaffMeshFacade()

    # Enqueue with minimum grace period (5 seconds)
    item = facade.enqueue_action(
        task_id="task-auto-dispatch",
        action_type=OutboundActionType.IM_BROADCAST,
        destination_target="#engineering-alerts",
        payload_text="System healthy",
        risk_tier=AudienceRiskTier.INTERNAL_SAFE,
        grace_period_seconds=5.0,
    )
    assert item.status == ActionBufferStatus.QUEUED_IN_GRACE_PERIOD

    # Wait for grace period to elapse
    time.sleep(5.1)

    dispatched_list = facade.poll_and_dispatch()
    assert any(x.action_id == item.action_id for x in dispatched_list)

    updated_item = facade.get_action(item.action_id)
    assert updated_item is not None
    assert updated_item.status == ActionBufferStatus.DISPATCHED_AFTER_GRACE


def test_emergency_e_brake_hard_stop() -> None:
    """Test out-of-band physical e-brake aborting all pending dispatches."""
    facade = OutboundEBrakeAndChiefOfStaffMeshFacade()

    # Enqueue 3 items
    item1 = facade.enqueue_action(
        task_id="task-1",
        action_type=OutboundActionType.EMAIL_DISPATCH,
        destination_target="press@media.org",
        payload_text="Embargoed release notes",
        risk_tier=AudienceRiskTier.EXTERNAL_UNTRUSTED,
        grace_period_seconds=30.0,
    )
    item2 = facade.enqueue_action(
        task_id="task-2",
        action_type=OutboundActionType.SOCIAL_POST,
        destination_target="x.com/api/v2/tweets",
        payload_text="Official announcement tweet",
        risk_tier=AudienceRiskTier.EXTERNAL_UNTRUSTED,
        grace_period_seconds=30.0,
    )

    queued = facade.list_queued_actions()
    assert len(queued) == 2

    # Trigger E-Brake!
    aborted_count = facade.trigger_e_brake(reason="CEO pressed emergency STOP hotkey")
    assert aborted_count == 2

    status: EBrakeStatus = facade.get_e_brake_status()
    assert status.is_e_brake_active is True
    assert status.actions_aborted_count == 2
    assert status.trigger_reason == "CEO pressed emergency STOP hotkey"

    # Verify individual action items transitioned to ABORTED_BY_E_BRAKE
    fetched1 = facade.get_action(item1.action_id)
    assert fetched1 is not None
    assert fetched1.status == ActionBufferStatus.ABORTED_BY_E_BRAKE

    fetched2 = facade.get_action(item2.action_id)
    assert fetched2 is not None
    assert fetched2.status == ActionBufferStatus.ABORTED_BY_E_BRAKE

    # While e-brake is active, new enqueue should be immediately aborted
    item3 = facade.enqueue_action(
        task_id="task-3",
        action_type=OutboundActionType.EMAIL_DISPATCH,
        destination_target="vendor@corp.internal",
        payload_text="Payment schedule",
        risk_tier=AudienceRiskTier.INTERNAL_SAFE,
    )
    assert item3.status == ActionBufferStatus.ABORTED_BY_E_BRAKE

    # Reset e-brake
    reset_ok = facade.reset_e_brake()
    assert reset_ok is True
    assert facade.get_e_brake_status().is_e_brake_active is False


def test_privacy_preserving_calendar_mesh() -> None:
    """Test zero-knowledge calendar negotiation finding optimal mutual slot without revealing events."""
    facade = OutboundEBrakeAndChiefOfStaffMeshFacade()

    # Party A slots (e.g. Chief of Staff for Alice)
    party_a_slots = (
        CalendarTimeSlot(slot_index=0, start_time_iso="2026-10-08T09:00:00Z", duration_minutes=30, is_free=True, preference_score=0.8),
        CalendarTimeSlot(slot_index=1, start_time_iso="2026-10-08T09:30:00Z", duration_minutes=30, is_free=False, preference_score=0.0),
        CalendarTimeSlot(slot_index=2, start_time_iso="2026-10-08T10:00:00Z", duration_minutes=30, is_free=True, preference_score=0.9),
        CalendarTimeSlot(slot_index=3, start_time_iso="2026-10-08T10:30:00Z", duration_minutes=30, is_free=True, preference_score=0.5),
    )

    # Party B slots (e.g. Chief of Staff for Bob)
    party_b_slots = (
        CalendarTimeSlot(slot_index=0, start_time_iso="2026-10-08T09:00:00Z", duration_minutes=30, is_free=False, preference_score=0.0),
        CalendarTimeSlot(slot_index=1, start_time_iso="2026-10-08T09:30:00Z", duration_minutes=30, is_free=True, preference_score=0.7),
        CalendarTimeSlot(slot_index=2, start_time_iso="2026-10-08T10:00:00Z", duration_minutes=30, is_free=True, preference_score=0.9),
        CalendarTimeSlot(slot_index=3, start_time_iso="2026-10-08T10:30:00Z", duration_minutes=30, is_free=True, preference_score=0.6),
    )

    result: CalendarNegotiationResult = facade.negotiate_calendar(
        party_a_id="cos-alice",
        party_b_id="cos-bob",
        party_a_slots=party_a_slots,
        party_b_slots=party_b_slots,
    )
    assert result.privacy_preserved is True
    # Mutually free slots should be slot 2 and slot 3
    assert len(result.matched_slots) == 2
    assert result.optimal_slot is not None
    # Slot 2 has combined score 0.9 + 0.9 = 1.8, vs slot 3 (0.5 + 0.6 = 1.1)
    assert result.optimal_slot.slot_index == 2
    assert result.optimal_slot.preference_score == 1.8
    assert result.optimal_slot.start_time_iso == "2026-10-08T10:00:00Z"
