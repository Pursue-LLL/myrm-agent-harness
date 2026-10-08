"""Atomic Hold-Resume state machine for headless agent interactive approval.

[POS] src/myrm_agent_harness/core/security/headless_interactive_approval/hold_state_machine.py
[INPUT] asyncio, time, uuid, myrm_agent_harness.core.security.headless_interactive_approval.types
[OUTPUT] HeadlessHoldStateMachine
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from typing import Final

from myrm_agent_harness.core.security.headless_interactive_approval.types import (
    ApprovalHoldStatus,
    ApprovalHoldTicket,
    RiskActionDescriptor,
)

logger: Final[logging.Logger] = logging.getLogger(__name__)


class HeadlessHoldStateMachine:
    """Manages transactional hold states, decision synchronization events, and shortlink tokens."""

    def __init__(self, base_approval_url: str = "http://localhost:3000/approve") -> None:
        self._base_approval_url = base_approval_url.rstrip("/")
        self._tickets: dict[str, ApprovalHoldTicket] = {}
        self._events: dict[str, asyncio.Event] = {}

    def create_hold_ticket(
        self,
        session_id: str,
        action: RiskActionDescriptor,
        timeout_seconds: float = 300.0,
    ) -> ApprovalHoldTicket:
        """Create an ephemeral hold ticket and register an async synchronization event."""
        tx_id = f"tx-{secrets.token_hex(8)}"
        now = time.time()
        expires_at = now + timeout_seconds

        shortlink_url = f"{self._base_approval_url}?tx={tx_id}"

        ticket = ApprovalHoldTicket(
            tx_id=tx_id,
            session_id=session_id,
            action=action,
            status=ApprovalHoldStatus.PENDING,
            shortlink_url=shortlink_url,
            created_at=now,
            expires_at=expires_at,
        )

        self._tickets[tx_id] = ticket
        self._events[tx_id] = asyncio.Event()

        logger.info(
            "Created hold ticket tx=%s session=%s tool=%s target='%s' (expires in %ds)",
            tx_id,
            session_id,
            action.tool_name,
            action.command_or_target,
            int(timeout_seconds),
        )
        return ticket

    def get_ticket(self, tx_id: str) -> ApprovalHoldTicket | None:
        """Fetch ticket by transaction ID, evaluating expiration if still pending."""
        ticket = self._tickets.get(tx_id)
        if ticket is None:
            return None

        now = time.time()
        if ticket.status == ApprovalHoldStatus.PENDING and now > ticket.expires_at:
            expired_ticket = ApprovalHoldTicket(
                tx_id=ticket.tx_id,
                session_id=ticket.session_id,
                action=ticket.action,
                status=ApprovalHoldStatus.TIMED_OUT,
                shortlink_url=ticket.shortlink_url,
                created_at=ticket.created_at,
                expires_at=ticket.expires_at,
                operator_decision_notes="Expired due to timeout before human response.",
                decided_by="system_timeout_daemon",
                decided_at=now,
            )
            self._tickets[tx_id] = expired_ticket
            # Wake up any waiting coroutine
            event = self._events.get(tx_id)
            if event and not event.is_set():
                event.set()
            return expired_ticket

        return ticket

    def submit_decision(
        self,
        tx_id: str,
        decision: ApprovalHoldStatus,
        operator: str,
        notes: str | None = None,
    ) -> ApprovalHoldTicket:
        """Atomically record operator decision and wake up waiting stream coroutines."""
        ticket = self.get_ticket(tx_id)
        if ticket is None:
            msg = f"Hold ticket '{tx_id}' not found."
            raise KeyError(msg)

        if ticket.status != ApprovalHoldStatus.PENDING:
            logger.warning(
                "Attempted decision on non-pending ticket tx=%s (status=%s)",
                tx_id,
                ticket.status.value,
            )
            return ticket

        now = time.time()
        updated_ticket = ApprovalHoldTicket(
            tx_id=ticket.tx_id,
            session_id=ticket.session_id,
            action=ticket.action,
            status=decision,
            shortlink_url=ticket.shortlink_url,
            created_at=ticket.created_at,
            expires_at=ticket.expires_at,
            operator_decision_notes=notes,
            decided_by=operator,
            decided_at=now,
        )

        self._tickets[tx_id] = updated_ticket
        logger.info(
            "Submitted decision for tx=%s: status=%s by '%s'",
            tx_id,
            decision.value,
            operator,
        )

        # Trigger synchronization event
        event = self._events.get(tx_id)
        if event and not event.is_set():
            event.set()

        return updated_ticket

    async def wait_for_decision(
        self,
        tx_id: str,
        timeout_seconds: float | None = None,
    ) -> ApprovalHoldTicket:
        """Asynchronously wait until a human decision is submitted or timeout occurs."""
        ticket = self.get_ticket(tx_id)
        if ticket is None:
            msg = f"Hold ticket '{tx_id}' not found."
            raise KeyError(msg)

        if ticket.status != ApprovalHoldStatus.PENDING:
            return ticket

        event = self._events.get(tx_id)
        if event is None:
            return ticket

        remaining_time = max(0.1, ticket.expires_at - time.time())
        effective_timeout = min(remaining_time, timeout_seconds) if timeout_seconds else remaining_time

        try:
            await asyncio.wait_for(event.wait(), timeout=effective_timeout)
        except TimeoutError:
            logger.warning("Wait timed out for hold ticket tx=%s", tx_id)
            return self.get_ticket(tx_id) or ticket

        return self.get_ticket(tx_id) or ticket
