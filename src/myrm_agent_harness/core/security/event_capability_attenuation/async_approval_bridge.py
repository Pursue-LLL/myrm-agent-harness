"""
[POS] src/myrm_agent_harness/core/security/event_capability_attenuation/async_approval_bridge.py
[INPUT] threading, time, uuid, typing, .types (ApprovalTicket, ApprovalTicketStatusEnum, ChannelNotificationTarget, TicketRiskLevelEnum)
[OUTPUT] AsyncApprovalBridge

Bridges unattended agents attempting attenuated high-risk actions to multi-channel
out-of-band mobile/chat approval workflows with single-use execution tokens.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import threading
import time
import uuid

from .types import (
    ApprovalTicket,
    ApprovalTicketStatusEnum,
    ChannelNotificationTarget,
    TicketRiskLevelEnum,
)


class AsyncApprovalBridge:
    """Manages lifecycle and channel dispatching of asynchronous approval tickets."""

    def __init__(self, default_ttl_seconds: float = 7200.0) -> None:
        self._lock = threading.RLock()
        self._default_ttl = default_ttl_seconds
        self._tickets: dict[str, ApprovalTicket] = {}
        self._one_time_tokens: dict[str, str] = {}  # token -> ticket_id

    def create_ticket(
        self,
        session_id: str,
        requested_tool: str,
        risk_level: TicketRiskLevelEnum,
        action_description: str,
        diff_payload: str,
        channels: list[ChannelNotificationTarget] | None = None,
        custom_ttl_seconds: float | None = None,
    ) -> ApprovalTicket:
        """Create a new pending approval ticket."""
        now = time.time()
        ttl = custom_ttl_seconds if custom_ttl_seconds is not None else self._default_ttl
        ticket_id = f"tkt-{uuid.uuid4().hex[:12]}"

        ticket = ApprovalTicket(
            ticket_id=ticket_id,
            session_id=session_id,
            requested_tool=requested_tool,
            risk_level=risk_level,
            action_description=action_description,
            diff_payload=diff_payload,
            created_at=now,
            expires_at=now + ttl,
            status=ApprovalTicketStatusEnum.PENDING,
            notification_channels=tuple(channels or []),
        )

        with self._lock:
            self._tickets[ticket_id] = ticket

        return ticket

    def get_ticket(self, ticket_id: str, current_time: float | None = None) -> ApprovalTicket | None:
        """Retrieve ticket, lazily evaluating expiration."""
        now = current_time if current_time is not None else time.time()
        with self._lock:
            ticket = self._tickets.get(ticket_id)
            if ticket is None:
                return None

            if ticket.status == ApprovalTicketStatusEnum.PENDING and now > ticket.expires_at:
                ticket = ApprovalTicket(
                    ticket_id=ticket.ticket_id,
                    session_id=ticket.session_id,
                    requested_tool=ticket.requested_tool,
                    risk_level=ticket.risk_level,
                    action_description=ticket.action_description,
                    diff_payload=ticket.diff_payload,
                    created_at=ticket.created_at,
                    expires_at=ticket.expires_at,
                    status=ApprovalTicketStatusEnum.EXPIRED,
                    decided_by="SYSTEM_TIMEOUT",
                    decision_reason="Ticket expired before human operator decision.",
                    notification_channels=ticket.notification_channels,
                )
                self._tickets[ticket_id] = ticket

            return ticket

    def list_pending_tickets(self) -> list[ApprovalTicket]:
        """List all currently active pending tickets."""
        now = time.time()
        active: list[ApprovalTicket] = []
        with self._lock:
            for tid in list(self._tickets.keys()):
                t = self.get_ticket(tid, current_time=now)
                if t is not None and t.status == ApprovalTicketStatusEnum.PENDING:
                    active.append(t)
        return active

    def approve_ticket(
        self,
        ticket_id: str,
        decided_by: str,
        decision_reason: str = "Approved by human operator via external channel.",
    ) -> tuple[ApprovalTicket | None, str | None]:
        """Approve a pending ticket and generate a one-time execution grant token."""
        ticket = self.get_ticket(ticket_id)
        if ticket is None:
            return None, None

        if ticket.status != ApprovalTicketStatusEnum.PENDING:
            return ticket, None

        token = f"grant-{uuid.uuid4().hex[:16]}"
        updated = ApprovalTicket(
            ticket_id=ticket.ticket_id,
            session_id=ticket.session_id,
            requested_tool=ticket.requested_tool,
            risk_level=ticket.risk_level,
            action_description=ticket.action_description,
            diff_payload=ticket.diff_payload,
            created_at=ticket.created_at,
            expires_at=ticket.expires_at,
            status=ApprovalTicketStatusEnum.APPROVED,
            decided_by=decided_by,
            decision_reason=decision_reason,
            notification_channels=ticket.notification_channels,
        )

        with self._lock:
            self._tickets[ticket_id] = updated
            self._one_time_tokens[token] = ticket_id

        return updated, token

    def reject_ticket(
        self,
        ticket_id: str,
        decided_by: str,
        decision_reason: str = "Rejected by human operator.",
    ) -> ApprovalTicket | None:
        """Reject a pending approval ticket."""
        ticket = self.get_ticket(ticket_id)
        if ticket is None:
            return None

        if ticket.status != ApprovalTicketStatusEnum.PENDING:
            return ticket

        updated = ApprovalTicket(
            ticket_id=ticket.ticket_id,
            session_id=ticket.session_id,
            requested_tool=ticket.requested_tool,
            risk_level=ticket.risk_level,
            action_description=ticket.action_description,
            diff_payload=ticket.diff_payload,
            created_at=ticket.created_at,
            expires_at=ticket.expires_at,
            status=ApprovalTicketStatusEnum.REJECTED,
            decided_by=decided_by,
            decision_reason=decision_reason,
            notification_channels=ticket.notification_channels,
        )

        with self._lock:
            self._tickets[ticket_id] = updated

        return updated

    def consume_one_time_token(self, token: str) -> str | None:
        """Consume single-use execution grant token, returning associated ticket_id if valid."""
        with self._lock:
            return self._one_time_tokens.pop(token, None)
