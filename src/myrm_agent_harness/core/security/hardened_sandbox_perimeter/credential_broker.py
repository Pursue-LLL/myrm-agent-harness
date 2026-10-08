"""
[POS] src/myrm_agent_harness/core/security/hardened_sandbox_perimeter/credential_broker.py
[INPUT] secrets, threading, time, typing, .types (BrokerCredentialTicket)
[OUTPUT] ZeroLeakCredentialBroker

Brokers ephemeral capability tokens and delegates signing out-of-band so that
high-value raw credentials (API keys, GitHub tokens, database passwords) are never
exposed as plaintext environment variables inside the agent sandbox container.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import secrets
import threading
import time

from .types import BrokerCredentialTicket


class ZeroLeakCredentialBroker:
    """Out-of-band host sidecar credential broker issuing short-lived ephemeral capability tickets."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._secrets_store: dict[str, str] = {}
        self._active_tickets: dict[str, BrokerCredentialTicket] = {}

    def register_secret(self, secret_alias: str, secret_value: str) -> None:
        """Register a high-value master secret alias in the secure host store."""
        with self._lock:
            self._secrets_store[secret_alias] = secret_value

    def has_secret(self, secret_alias: str) -> bool:
        """Check whether a secret alias is configured."""
        with self._lock:
            return secret_alias in self._secrets_store

    def mint_ticket(
        self,
        secret_alias: str,
        allowed_scopes: list[str],
        ttl_seconds: float = 300.0,
        current_time: float | None = None,
    ) -> BrokerCredentialTicket:
        """Issue a short-lived scoped ephemeral ticket for sandbox runtime operations."""
        now = current_time if current_time is not None else time.time()
        with self._lock:
            if secret_alias not in self._secrets_store:
                raise ValueError(f"Secret alias '{secret_alias}' is not registered in credential vault.")

            ticket_id = f"tkt-{secrets.token_hex(8)}"
            ephemeral_token = f"ept-{secrets.token_urlsafe(24)}"
            ticket = BrokerCredentialTicket(
                ticket_id=ticket_id,
                secret_alias=secret_alias,
                ephemeral_token=ephemeral_token,
                expires_at=now + ttl_seconds,
                allowed_scopes=list(allowed_scopes),
            )
            self._active_tickets[ticket_id] = ticket
            return ticket

    def verify_ticket(
        self,
        ticket_id: str,
        required_scope: str | None = None,
        current_time: float | None = None,
    ) -> bool:
        """Verify ticket validity, expiry, and scope authorization."""
        now = current_time if current_time is not None else time.time()
        with self._lock:
            ticket = self._active_tickets.get(ticket_id)
            if ticket is None:
                return False

            if now >= ticket.expires_at:
                # Expired ticket
                del self._active_tickets[ticket_id]
                return False

            return (
                required_scope is None
                or "*" in ticket.allowed_scopes
                or required_scope in ticket.allowed_scopes
            )

    def revoke_ticket(self, ticket_id: str) -> bool:
        """Explicitly revoke an active ticket ahead of expiration."""
        with self._lock:
            if ticket_id in self._active_tickets:
                del self._active_tickets[ticket_id]
                return True
            return False

    def clean_expired_tickets(self, current_time: float | None = None) -> int:
        """Sweep and purge expired tickets from memory."""
        now = current_time if current_time is not None else time.time()
        with self._lock:
            expired_ids = [
                tid for tid, tkt in self._active_tickets.items() if now >= tkt.expires_at
            ]
            for tid in expired_ids:
                del self._active_tickets[tid]
            return len(expired_ids)
