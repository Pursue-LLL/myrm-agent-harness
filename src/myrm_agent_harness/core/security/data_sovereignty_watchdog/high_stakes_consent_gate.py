"""
[POS] src/myrm_agent_harness/core/security/data_sovereignty_watchdog/high_stakes_consent_gate.py
[INPUT] time, uuid, typing
[OUTPUT] HighStakesConsentGate

High-stakes financial and account mutation consent gate.
Enforces mandatory human operator authorization before autonomous execution of subscription cancellations,
refund disputes, and payment method changes.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import logging
import time
import uuid

from .types import HighStakesActionType, HighStakesConsentTicket

logger = logging.getLogger(__name__)


class HighStakesConsentGate:
    """Manages one-time human consent tickets for irreversible financial and account operations."""

    def __init__(self) -> None:
        self._pending_tickets: dict[str, HighStakesConsentTicket] = {}
        self._history_tickets: dict[str, HighStakesConsentTicket] = {}

    def create_consent_ticket(
        self,
        action_type: HighStakesActionType,
        service_name: str,
        financial_impact_cents: int,
        payload_summary: str,
    ) -> HighStakesConsentTicket:
        """Lock high-stakes operation behind a pending consent ticket requiring explicit human click/authorization."""
        ticket_id = f"ticket-{uuid.uuid4().hex[:12]}"
        ticket = HighStakesConsentTicket(
            ticket_id=ticket_id,
            action_type=action_type,
            service_name=service_name,
            financial_impact_cents=financial_impact_cents,
            payload_summary=payload_summary,
            is_approved=False,
            is_denied=False,
            created_at=time.time(),
        )

        self._pending_tickets[ticket_id] = ticket
        logger.info(
            "Created high-stakes consent ticket %s (action=%s, service=%s, impact=%d cents)",
            ticket_id,
            action_type.value,
            service_name,
            financial_impact_cents,
        )
        return ticket

    def approve_ticket(self, ticket_id: str) -> HighStakesConsentTicket:
        """Operator explicitly authorizes the high-stakes transaction."""
        pending = self._pending_tickets.pop(ticket_id, None)
        if pending is None:
            raise KeyError(f"Pending consent ticket '{ticket_id}' not found.")

        approved_ticket = HighStakesConsentTicket(
            ticket_id=pending.ticket_id,
            action_type=pending.action_type,
            service_name=pending.service_name,
            financial_impact_cents=pending.financial_impact_cents,
            payload_summary=pending.payload_summary,
            is_approved=True,
            is_denied=False,
            created_at=pending.created_at,
        )
        self._history_tickets[ticket_id] = approved_ticket
        logger.info("Human operator approved high-stakes ticket %s", ticket_id)
        return approved_ticket

    def deny_ticket(self, ticket_id: str) -> HighStakesConsentTicket:
        """Operator explicitly rejects the high-stakes transaction."""
        pending = self._pending_tickets.pop(ticket_id, None)
        if pending is None:
            raise KeyError(f"Pending consent ticket '{ticket_id}' not found.")

        denied_ticket = HighStakesConsentTicket(
            ticket_id=pending.ticket_id,
            action_type=pending.action_type,
            service_name=pending.service_name,
            financial_impact_cents=pending.financial_impact_cents,
            payload_summary=pending.payload_summary,
            is_approved=False,
            is_denied=True,
            created_at=pending.created_at,
        )
        self._history_tickets[ticket_id] = denied_ticket
        logger.info("Human operator denied high-stakes ticket %s", ticket_id)
        return denied_ticket

    def get_ticket(self, ticket_id: str) -> HighStakesConsentTicket | None:
        """Fetch ticket by ID."""
        return self._pending_tickets.get(ticket_id) or self._history_tickets.get(ticket_id)

    def list_pending_tickets(self) -> list[HighStakesConsentTicket]:
        """List all operations currently awaiting human consent."""
        return list(self._pending_tickets.values())
