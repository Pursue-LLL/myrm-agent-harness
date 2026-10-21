"""Single-use ticket manager implementing DSH Data Agent §9 three-token chain.

[INPUT]
- .types::SingleUseTicket, TicketStatus, TokenType

[OUTPUT]
- SingleUseTicketManager: Manager handling ticket minting, digest binding, and atomic consumption.
- compute_content_digest: Cryptographic canonical argument digest computation.
- get_single_use_ticket_manager: Process-level singleton getter.

[POS]
agent/security/single_use_tickets/manager.py
Zero-leakage, single-use atomic permission gate.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import uuid

from .types import SingleUseTicket, TicketStatus, TokenType

logger = logging.getLogger(__name__)

_DEFAULT_TICKET_TTL_SECONDS = 60.0


def compute_content_digest(tool_name: str, args: object) -> str:
    """Compute a canonical SHA-256 digest binding tool name and its arguments.

    Prevents parameter tampering and replay attacks.
    """
    canonical: str
    if isinstance(args, str):
        canonical = args.strip()
    elif isinstance(args, dict):
        try:
            canonical = json.dumps(args, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        except Exception:
            canonical = str(sorted(args.items()))
    else:
        canonical = str(args)

    payload = f"{tool_name}:{canonical}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class SingleUseTicketManager:
    """Thread-safe ticket lifecycle coordinator."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._tickets: dict[str, dict[str, SingleUseTicket]] = {}

    def mint_ticket(
        self,
        session_id: str,
        token_type: TokenType,
        tool_name: str,
        args: object,
        *,
        ttl_seconds: float = _DEFAULT_TICKET_TTL_SECONDS,
        bound_credential_handles: list[str] | None = None,
    ) -> SingleUseTicket:
        """Mint a new single-use ticket bound to session, tool name, and content digest."""
        digest = compute_content_digest(tool_name, args)
        ticket_id = f"ticket_{token_type.value[:4]}_{uuid.uuid4().hex[:12]}"

        ticket = SingleUseTicket(
            ticket_id=ticket_id,
            session_id=session_id,
            token_type=token_type,
            tool_name=tool_name,
            content_digest=digest,
            ttl_seconds=ttl_seconds,
            bound_credential_handles=list(bound_credential_handles or []),
        )

        with self._lock:
            if session_id not in self._tickets:
                self._tickets[session_id] = {}
            self._tickets[session_id][ticket_id] = ticket

        logger.debug(
            "[SINGLE_USE_TICKET] Minted ticket '%s' for session '%s' (type=%s, tool=%s, digest=%s...)",
            ticket_id,
            session_id,
            token_type.value,
            tool_name,
            digest[:8],
        )
        return ticket

    def verify_and_consume(
        self,
        session_id: str,
        ticket_id: str,
        token_type: TokenType,
        tool_name: str,
        args: object,
    ) -> tuple[bool, str, list[str]]:
        """Verify ticket matches and atomically consume it.

        Returns:
            tuple[bool, str, list[str]]: (success, reason, bound_credential_handles)
        """
        with self._lock:
            session_tickets = self._tickets.get(session_id)
            if not session_tickets or ticket_id not in session_tickets:
                return False, f"Ticket '{ticket_id}' not found in session '{session_id}'.", []

            ticket = session_tickets[ticket_id]

            if ticket.status == TicketStatus.CONSUMED:
                return False, f"Ticket '{ticket_id}' has already been consumed.", []
            if ticket.status == TicketStatus.REVOKED:
                return False, f"Ticket '{ticket_id}' has been revoked.", []
            if ticket.is_expired:
                ticket.status = TicketStatus.EXPIRED
                return False, f"Ticket '{ticket_id}' has expired (TTL={ticket.ttl_seconds}s).", []

            if ticket.token_type != token_type:
                return (
                    False,
                    f"Token type mismatch: ticket is '{ticket.token_type.value}', expected '{token_type.value}'.",
                    [],
                )
            if ticket.tool_name != tool_name:
                return (
                    False,
                    f"Tool mismatch: ticket is bound to '{ticket.tool_name}', got '{tool_name}'.",
                    [],
                )

            incoming_digest = compute_content_digest(tool_name, args)
            if ticket.content_digest != incoming_digest:
                logger.warning(
                    "[SINGLE_USE_TICKET] Digest mismatch! Ticket digest=%s, execution digest=%s",
                    ticket.content_digest,
                    incoming_digest,
                )
                return (
                    False,
                    "Execution parameters do not match ticket content digest (tampering or replay detected).",
                    [],
                )

            # Atomically mark as consumed
            ticket.status = TicketStatus.CONSUMED
            handles = list(ticket.bound_credential_handles)
            logger.info(
                "[SINGLE_USE_TICKET] Successfully verified and consumed ticket '%s' for '%s'",
                ticket_id,
                tool_name,
            )
            return True, "Ticket verified and consumed successfully.", handles

    def revoke_ticket(self, session_id: str, ticket_id: str) -> bool:
        """Explicitly revoke a ticket."""
        with self._lock:
            session_tickets = self._tickets.get(session_id)
            if not session_tickets or ticket_id not in session_tickets:
                return False
            ticket = session_tickets[ticket_id]
            ticket.status = TicketStatus.REVOKED
            logger.info("[SINGLE_USE_TICKET] Revoked ticket '%s' in session '%s'", ticket_id, session_id)
            return True

    def purge_session(self, session_id: str) -> int:
        """Purge and revoke all tickets for a session."""
        with self._lock:
            session_tickets = self._tickets.pop(session_id, None)
            if not session_tickets:
                return 0
            count = len(session_tickets)
            for ticket in session_tickets.values():
                ticket.status = TicketStatus.REVOKED
            logger.info("[SINGLE_USE_TICKET] Purged %d tickets for session '%s'", count, session_id)
            return count

    def cleanup_expired(self) -> int:
        """Clean up expired tickets across all sessions."""
        with self._lock:
            cleaned = 0
            for _session_id, session_tickets in list(self._tickets.items()):
                for _ticket_id, ticket in list(session_tickets.items()):
                    if ticket.is_expired and ticket.status == TicketStatus.ISSUED:
                        ticket.status = TicketStatus.EXPIRED
                        cleaned += 1
            if cleaned > 0:
                logger.info("[SINGLE_USE_TICKET] Cleaned up %d expired tickets", cleaned)
            return cleaned


_global_ticket_manager: SingleUseTicketManager | None = None
_manager_lock = threading.Lock()


def get_single_use_ticket_manager() -> SingleUseTicketManager:
    """Return process-wide singleton ticket manager."""
    global _global_ticket_manager
    if _global_ticket_manager is None:
        with _manager_lock:
            if _global_ticket_manager is None:
                _global_ticket_manager = SingleUseTicketManager()
    return _global_ticket_manager
