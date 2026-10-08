"""
[POS] src/myrm_agent_harness/core/security/event_capability_attenuation/facade.py
[INPUT] threading, typing, .async_approval_bridge, .attenuation_capsule, .event_signature_verifier, .types
[OUTPUT] EventCapabilityAttenuationFacade

Unified Facade for Event-Triggered Capability Attenuation and Multi-Channel Async Approval Bridge.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import threading

from .async_approval_bridge import AsyncApprovalBridge
from .attenuation_capsule import CapabilityAttenuationCapsule
from .event_signature_verifier import EventSignatureVerifier
from .types import (
    ApprovalTicket,
    CapabilityAttenuationMetrics,
    ChannelNotificationTarget,
    EventPayloadDescriptor,
    EventTrustScopeEnum,
    TicketRiskLevelEnum,
)


class EventCapabilityAttenuationFacade:
    """Coordinates event authentication, capability attenuation, and unattended out-of-band approvals."""

    def __init__(self, default_ticket_ttl: float = 7200.0) -> None:
        self._lock = threading.Lock()
        self._verifier = EventSignatureVerifier()
        self._capsule = CapabilityAttenuationCapsule()
        self._bridge = AsyncApprovalBridge(default_ttl_seconds=default_ticket_ttl)
        self._metrics = CapabilityAttenuationMetrics()

    def register_event_secret(self, source_name: str, secret_key: str | bytes) -> None:
        """Register shared secret for an event source."""
        self._verifier.register_source_secret(source_name, secret_key)

    def verify_and_ingest_event(
        self,
        event_id: str,
        source_name: str,
        event_type: str,
        timestamp: float,
        raw_payload_bytes: bytes,
        signature: str | None,
        auto_bind_session_id: str | None = None,
    ) -> EventPayloadDescriptor:
        """Verify HMAC signature and optionally bind session to LOW_TRUST_EVENT_SCOPE."""
        descriptor = self._verifier.verify_event(
            event_id=event_id,
            source_name=source_name,
            event_type=event_type,
            timestamp=timestamp,
            raw_payload_bytes=raw_payload_bytes,
            signature=signature,
        )

        with self._lock:
            self._metrics.total_events_received += 1
            if descriptor.is_verified:
                self._metrics.verified_events_count += 1
            else:
                self._metrics.rejected_signature_events += 1

        if auto_bind_session_id is not None:
            scope = (
                EventTrustScopeEnum.LOW_TRUST_EVENT_SCOPE
                if descriptor.is_verified
                else EventTrustScopeEnum.ISOLATED_QUARANTINE
            )
            self._capsule.set_session_scope(auto_bind_session_id, scope)
            with self._lock:
                self._metrics.attenuated_executions_count += 1

        return descriptor

    def set_session_scope(self, session_id: str, scope: EventTrustScopeEnum) -> None:
        """Set explicit session scope."""
        self._capsule.set_session_scope(session_id, scope)

    def get_session_scope(self, session_id: str) -> EventTrustScopeEnum:
        """Get active session scope."""
        return self._capsule.get_session_scope(session_id)

    def evaluate_tool(
        self, session_id: str, tool_name: str
    ) -> tuple[bool, str, TicketRiskLevelEnum]:
        """Evaluate whether tool access is permissible under current attenuation scope."""
        return self._capsule.evaluate_tool_access(session_id, tool_name)

    def create_approval_ticket(
        self,
        session_id: str,
        requested_tool: str,
        risk_level: TicketRiskLevelEnum,
        action_description: str,
        diff_payload: str,
        channels: list[ChannelNotificationTarget] | None = None,
        custom_ttl_seconds: float | None = None,
    ) -> ApprovalTicket:
        """Create pending out-of-band approval ticket for attenuated agent action."""
        ticket = self._bridge.create_ticket(
            session_id=session_id,
            requested_tool=requested_tool,
            risk_level=risk_level,
            action_description=action_description,
            diff_payload=diff_payload,
            channels=channels,
            custom_ttl_seconds=custom_ttl_seconds,
        )
        with self._lock:
            self._metrics.tickets_created += 1
        return ticket

    def get_ticket(self, ticket_id: str) -> ApprovalTicket | None:
        """Inspect approval ticket."""
        return self._bridge.get_ticket(ticket_id)

    def list_pending_tickets(self) -> list[ApprovalTicket]:
        """List active pending approval tickets."""
        return self._bridge.list_pending_tickets()

    def approve_ticket(
        self,
        ticket_id: str,
        decided_by: str,
        decision_reason: str = "Approved by human operator via external channel.",
    ) -> tuple[ApprovalTicket | None, str | None]:
        """Approve ticket and obtain single-use execution grant token."""
        ticket, token = self._bridge.approve_ticket(
            ticket_id=ticket_id,
            decided_by=decided_by,
            decision_reason=decision_reason,
        )
        if ticket is not None and token is not None:
            with self._lock:
                self._metrics.tickets_approved += 1
        return ticket, token

    def reject_ticket(
        self,
        ticket_id: str,
        decided_by: str,
        decision_reason: str = "Rejected by human operator.",
    ) -> ApprovalTicket | None:
        """Reject approval ticket."""
        ticket = self._bridge.reject_ticket(
            ticket_id=ticket_id,
            decided_by=decided_by,
            decision_reason=decision_reason,
        )
        if ticket is not None:
            with self._lock:
                self._metrics.tickets_rejected += 1
        return ticket

    def verify_and_consume_token(self, token: str) -> str | None:
        """Validate and consume single-use execution token."""
        return self._bridge.consume_one_time_token(token)

    def get_metrics(self) -> CapabilityAttenuationMetrics:
        """Snapshot of operational metrics."""
        with self._lock:
            return CapabilityAttenuationMetrics(
                total_events_received=self._metrics.total_events_received,
                verified_events_count=self._metrics.verified_events_count,
                rejected_signature_events=self._metrics.rejected_signature_events,
                attenuated_executions_count=self._metrics.attenuated_executions_count,
                tickets_created=self._metrics.tickets_created,
                tickets_approved=self._metrics.tickets_approved,
                tickets_rejected=self._metrics.tickets_rejected,
                tickets_expired=self._metrics.tickets_expired,
            )
