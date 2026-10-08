"""
[POS] src/myrm_agent_harness/core/security/outbound_ebrake_mesh/facade.py
[INPUT] types, outbound_ghost_gate, grace_period_buffer, privacy_calendar_mesh
[OUTPUT] OutboundEBrakeAndChiefOfStaffMeshFacade

Unified facade aggregating pre-flight ghost inspection, cooldown grace buffering, physical e-brake, and calendar mesh.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from .grace_period_buffer import OutboundGracePeriodBuffer
from .outbound_ghost_gate import OutboundSideEffectGhostGate
from .privacy_calendar_mesh import PrivacyPreservingCalendarMesh
from .types import (
    AudienceRiskTier,
    CalendarNegotiationResult,
    CalendarTimeSlot,
    EBrakeStatus,
    GhostInspectionVerdict,
    OutboundActionItem,
    OutboundActionType,
    OutboundEBrakeMetrics,
)


class OutboundEBrakeAndChiefOfStaffMeshFacade:
    """Unified entrypoint for irreversible outbound action safeguards, physical stop, and calendar mesh."""

    def __init__(
        self,
        internal_domains: tuple[str, ...] | None = None,
        trusted_external_domains: tuple[str, ...] | None = None,
    ) -> None:
        self._metrics = OutboundEBrakeMetrics()
        self._ghost_gate = OutboundSideEffectGhostGate(
            internal_domains=internal_domains,
            trusted_external_domains=trusted_external_domains,
            metrics=self._metrics,
        )
        self._buffer = OutboundGracePeriodBuffer(metrics=self._metrics)
        self._calendar_mesh = PrivacyPreservingCalendarMesh(metrics=self._metrics)

    @property
    def metrics(self) -> OutboundEBrakeMetrics:
        """Shared operational metrics."""
        return self._metrics

    def inspect_outbound_action(
        self,
        action_type: OutboundActionType,
        destination_target: str,
        payload_text: str,
    ) -> GhostInspectionVerdict:
        """Inspect outbound action for audience boundary and secret token exfiltration risks."""
        return self._ghost_gate.inspect_outbound_action(
            action_type=action_type,
            destination_target=destination_target,
            payload_text=payload_text,
        )

    def enqueue_action(
        self,
        task_id: str,
        action_type: OutboundActionType,
        destination_target: str,
        payload_text: str,
        risk_tier: AudienceRiskTier,
        grace_period_seconds: float = OutboundGracePeriodBuffer.DEFAULT_GRACE_PERIOD_SECONDS,
    ) -> OutboundActionItem:
        """Enqueue inspected action into cooldown buffer with grace countdown."""
        return self._buffer.enqueue_action(
            task_id=task_id,
            action_type=action_type,
            destination_target=destination_target,
            payload_text=payload_text,
            risk_tier=risk_tier,
            grace_period_seconds=grace_period_seconds,
        )

    def cancel_action(
        self, action_id: str, reason: str = "User manual cancel"
    ) -> bool:
        """Cancel queued action during cooldown."""
        return self._buffer.cancel_action(action_id=action_id, reason=reason)

    def flush_action(self, action_id: str) -> bool:
        """Bypass remaining grace cooldown and immediately dispatch action."""
        return self._buffer.flush_action(action_id=action_id)

    def poll_and_dispatch(self) -> list[OutboundActionItem]:
        """Poll and transition expired items into dispatched state."""
        return self._buffer.poll_and_dispatch()

    def trigger_e_brake(
        self, reason: str = "Out-of-band physical emergency stop"
    ) -> int:
        """Trigger emergency stop: instantly abort all queued outbound actions."""
        return self._buffer.trigger_e_brake(reason=reason)

    def reset_e_brake(self) -> bool:
        """Reset emergency brake."""
        return self._buffer.reset_e_brake()

    def get_e_brake_status(self) -> EBrakeStatus:
        """Retrieve emergency brake status."""
        return self._buffer.get_e_brake_status()

    def get_action(self, action_id: str) -> OutboundActionItem | None:
        """Lookup action item by ID."""
        return self._buffer.get_action(action_id=action_id)

    def list_queued_actions(self) -> tuple[OutboundActionItem, ...]:
        """List currently pending actions waiting in cooldown."""
        return self._buffer.list_queued_actions()

    def negotiate_calendar(
        self,
        party_a_id: str,
        party_b_id: str,
        party_a_slots: tuple[CalendarTimeSlot, ...],
        party_b_slots: tuple[CalendarTimeSlot, ...],
    ) -> CalendarNegotiationResult:
        """Perform zero-knowledge calendar negotiation between agents."""
        return self._calendar_mesh.negotiate_slots(
            party_a_id=party_a_id,
            party_b_id=party_b_id,
            party_a_slots=party_a_slots,
            party_b_slots=party_b_slots,
        )
