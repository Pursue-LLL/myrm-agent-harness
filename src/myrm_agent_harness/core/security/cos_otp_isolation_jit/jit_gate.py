"""Intent-bound JIT authorization gate with burn-after-reading single-use semantics."""

from __future__ import annotations

import logging
import secrets
import time

from myrm_agent_harness.core.security.cos_otp_isolation_jit.types import (
    JitOtpTicket,
)

logger = logging.getLogger(__name__)


class IntentBoundJitAuthorizationGate:
    """Manages ephemeral JIT authorization tickets bound to verified user transactional intent."""

    def __init__(self) -> None:
        # Key: ticket_id -> JitOtpTicket
        self._tickets: dict[str, JitOtpTicket] = {}

    def issue_ticket(
        self,
        session_id: str,
        target_domain: str,
        purpose: str,
        otp_code: str,
        validity_seconds: int = 60,
    ) -> JitOtpTicket:
        """Issue a time-bound single-use authorization ticket for explicit user purchase/login flow."""
        now = time.time()
        ticket_id = f"jit-otp-{secrets.token_hex(8)}"
        expires_at = now + validity_seconds

        ticket = JitOtpTicket(
            ticket_id=ticket_id,
            session_id=session_id,
            target_domain=target_domain.strip().lower(),
            purpose=purpose,
            otp_code=otp_code,
            issued_at=now,
            expires_at=expires_at,
            consumed=False,
        )

        self._tickets[ticket_id] = ticket
        logger.info(
            "Issued JIT OTP ticket '%s' for session '%s' targeting '%s', valid for %ds.",
            ticket_id,
            session_id,
            target_domain,
            validity_seconds,
        )
        return ticket

    def consume_ticket(self, ticket_id: str, target_domain: str) -> str | None:
        """Consume a ticket in burn-after-reading fashion.

        Returns:
            The raw OTP code if valid, bound to the target domain, and unexpired;
            None if invalid, already consumed, expired, or domain mismatched.
        """
        ticket = self._tickets.get(ticket_id)
        if ticket is None:
            logger.warning("Attempted consumption of nonexistent ticket '%s'.", ticket_id)
            return None

        if ticket.consumed:
            logger.warning("Attempted reuse of already consumed JIT ticket '%s'.", ticket_id)
            return None

        now = time.time()
        if now > ticket.expires_at:
            logger.warning("Attempted consumption of expired JIT ticket '%s'.", ticket_id)
            return None

        normalized_domain = target_domain.strip().lower()
        if ticket.target_domain != normalized_domain:
            logger.warning(
                "Domain mismatch on JIT ticket '%s': expected '%s', got '%s'.",
                ticket_id,
                ticket.target_domain,
                normalized_domain,
            )
            return None

        # Burn-after-reading: mark as consumed
        consumed_ticket = JitOtpTicket(
            ticket_id=ticket.ticket_id,
            session_id=ticket.session_id,
            target_domain=ticket.target_domain,
            purpose=ticket.purpose,
            otp_code="",  # Clear raw code in state
            issued_at=ticket.issued_at,
            expires_at=ticket.expires_at,
            consumed=True,
        )
        self._tickets[ticket_id] = consumed_ticket

        logger.info("Successfully consumed and burned JIT OTP ticket '%s'.", ticket_id)
        return ticket.otp_code

    def revoke_ticket(self, ticket_id: str) -> bool:
        """Explicitly revoke a pending JIT ticket."""
        if ticket_id in self._tickets:
            del self._tickets[ticket_id]
            return True
        return False
