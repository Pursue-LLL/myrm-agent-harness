"""
[POS] src/myrm_agent_harness/core/security/subdomain_ticket_gateway/ticket_exchange_manager.py
[INPUT] hashlib, hmac, logging, time, uuid, typing, .types
[OUTPUT] ShortLivedTicketExchangeManager

Cryptographic manager for short-lived, anti-replay ticket issuance and session minting.
Enforces 30-second single-use TTL, client IP and fingerprint bindings, and issues
isolated subdomain HttpOnly session tokens completely decoupled from master tokens.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
import uuid

from .types import (
    InstanceSessionContext,
    OneTimeExchangeTicket,
    TicketValidationStatus,
)

logger = logging.getLogger(__name__)


class ShortLivedTicketExchangeManager:
    """Manages short-lived anti-replay tickets and isolated subdomain sessions."""

    DEFAULT_TICKET_TTL_SECONDS: float = 30.0
    DEFAULT_SESSION_TTL_SECONDS: float = 3600.0

    def __init__(
        self,
        secret_key: bytes | None = None,
        ticket_ttl_seconds: float = DEFAULT_TICKET_TTL_SECONDS,
        session_ttl_seconds: float = DEFAULT_SESSION_TTL_SECONDS,
    ) -> None:
        self._secret_key = secret_key or b"myrm-subdomain-gateway-secret-salt-2026"
        self._ticket_ttl_seconds = ticket_ttl_seconds
        self._session_ttl_seconds = session_ttl_seconds
        self._tickets: dict[str, OneTimeExchangeTicket] = {}
        self._active_sessions: dict[str, InstanceSessionContext] = {}

    def issue_ticket(
        self,
        master_user_id: str,
        target_instance_id: str,
        client_ip: str,
        client_fingerprint: str,
    ) -> OneTimeExchangeTicket:
        """Issue a short-lived, single-use ticket cryptographically bound to client fingerprint."""
        now = time.time()
        ticket_id = f"tkt-{uuid.uuid4().hex[:16]}"
        expires_at = now + self._ticket_ttl_seconds

        signature = self._compute_ticket_signature(
            ticket_id=ticket_id,
            master_user_id=master_user_id,
            target_instance_id=target_instance_id,
            client_ip=client_ip,
            client_fingerprint=client_fingerprint,
            expires_at=expires_at,
        )

        ticket = OneTimeExchangeTicket(
            ticket_id=ticket_id,
            master_user_id=master_user_id,
            target_instance_id=target_instance_id,
            client_ip=client_ip,
            client_fingerprint=client_fingerprint,
            expires_at=expires_at,
            signature=signature,
            is_consumed=False,
        )
        self._tickets[ticket_id] = ticket

        logger.info(
            "Issued exchange ticket '%s' for user '%s' targeting instance '%s' (expires in %.1fs).",
            ticket_id,
            master_user_id,
            target_instance_id,
            self._ticket_ttl_seconds,
        )
        return ticket

    def redeem_ticket(
        self,
        ticket_id: str,
        client_ip: str,
        client_fingerprint: str,
    ) -> tuple[TicketValidationStatus, InstanceSessionContext | None]:
        """Validate and consume ticket atomically to mint an isolated instance session."""
        now = time.time()
        ticket = self._tickets.get(ticket_id)

        if ticket is None or ticket.is_consumed:
            logger.warning("Ticket redemption failed: ticket '%s' is missing or already consumed.", ticket_id)
            return TicketValidationStatus.ALREADY_CONSUMED, None

        if now > ticket.expires_at:
            logger.warning("Ticket redemption failed: ticket '%s' has expired.", ticket_id)
            return TicketValidationStatus.EXPIRED, None

        # Verify cryptographic HMAC signature
        expected_sig = self._compute_ticket_signature(
            ticket_id=ticket.ticket_id,
            master_user_id=ticket.master_user_id,
            target_instance_id=ticket.target_instance_id,
            client_ip=ticket.client_ip,
            client_fingerprint=ticket.client_fingerprint,
            expires_at=ticket.expires_at,
        )
        if not hmac.compare_digest(ticket.signature, expected_sig):
            logger.error("Ticket redemption failed: ticket '%s' has invalid cryptographic signature.", ticket_id)
            return TicketValidationStatus.INVALID_SIGNATURE, None

        # Verify client binding
        if ticket.client_ip != client_ip or ticket.client_fingerprint != client_fingerprint:
            logger.warning(
                "Ticket redemption failed: client IP/fingerprint mismatch for ticket '%s'.",
                ticket_id,
            )
            return TicketValidationStatus.FINGERPRINT_MISMATCH, None

        # Mark consumed atomically
        consumed_ticket = OneTimeExchangeTicket(
            ticket_id=ticket.ticket_id,
            master_user_id=ticket.master_user_id,
            target_instance_id=ticket.target_instance_id,
            client_ip=ticket.client_ip,
            client_fingerprint=ticket.client_fingerprint,
            expires_at=ticket.expires_at,
            signature=ticket.signature,
            is_consumed=True,
        )
        self._tickets[ticket_id] = consumed_ticket

        # Mint isolated subdomain session
        session_id = f"inst-sess-{uuid.uuid4().hex[:16]}"
        session_context = InstanceSessionContext(
            session_id=session_id,
            instance_id=ticket.target_instance_id,
            user_id=ticket.master_user_id,
            issued_at=now,
            expires_at=now + self._session_ttl_seconds,
            is_revoked=False,
        )
        self._active_sessions[session_id] = session_context

        logger.info(
            "Successfully redeemed ticket '%s' and minted isolated instance session '%s'.",
            ticket_id,
            session_id,
        )
        return TicketValidationStatus.VALID, session_context

    def validate_instance_session(self, session_id: str, instance_id: str) -> bool:
        """Verify validity and instance scoping of an active subdomain session."""
        now = time.time()
        session = self._active_sessions.get(session_id)
        if session is None or session.is_revoked:
            return False
        if now > session.expires_at:
            return False
        return session.instance_id == instance_id

    def revoke_session(self, session_id: str) -> bool:
        """Revoke an active instance session."""
        session = self._active_sessions.get(session_id)
        if session is None:
            return False
        revoked = InstanceSessionContext(
            session_id=session.session_id,
            instance_id=session.instance_id,
            user_id=session.user_id,
            issued_at=session.issued_at,
            expires_at=session.expires_at,
            is_revoked=True,
        )
        self._active_sessions[session_id] = revoked
        logger.info("Revoked instance session '%s'.", session_id)
        return True

    def _compute_ticket_signature(
        self,
        ticket_id: str,
        master_user_id: str,
        target_instance_id: str,
        client_ip: str,
        client_fingerprint: str,
        expires_at: float,
    ) -> str:
        """Compute HMAC-SHA256 signature over ticket attributes."""
        canonical = (
            f"{ticket_id}:{master_user_id}:{target_instance_id}:"
            f"{client_ip}:{client_fingerprint}:{expires_at:.4f}"
        )
        return hmac.new(self._secret_key, canonical.encode("utf-8"), hashlib.sha256).hexdigest()
