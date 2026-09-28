"""Types for single-use execution tickets and DSH three-token chain.

[INPUT]
- None (standard library)

[OUTPUT]
- TokenType: DSH Data Agent §9 token categories (CONFIRMATION, QUERY, EXPLORATION).
- TicketStatus: Single-use ticket lifecycle states (ISSUED, CONSUMED, EXPIRED, REVOKED).
- SingleUseTicket: Cryptographically bound single-use execution ticket.

[POS]
agent/security/single_use_tickets/types.py
Precise single-use scope security models.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class TokenType(StrEnum):
    """Three-token chain categories (DSH Data Agent §9).

    CONFIRMATION: Bounds semantic approval intents (e.g. destructive actions, writes).
    QUERY: Bounds raw query/script content (e.g. SQL statements, shell commands).
    EXPLORATION: Bounds exploratory inspection scopes (e.g. directory trees, read-only probes).
    """

    CONFIRMATION = "confirmation"
    QUERY = "query"
    EXPLORATION = "exploration"


class TicketStatus(StrEnum):
    """Lifecycle status of a single-use permission ticket."""

    ISSUED = "issued"
    CONSUMED = "consumed"
    EXPIRED = "expired"
    REVOKED = "revoked"


@dataclass
class SingleUseTicket:
    """A cryptographically bound single-use execution ticket.

    Guarantees:
    - Atomically consumed: Can only be consumed once, immediately transitions to CONSUMED.
    - Content-bound: Stored with SHA-256 digest of canonical execution arguments.
    - Time-bounded: Auto-expires after ttl_seconds.
    - Linked credentials: Carries ephemeral credential handles that must be zeroized after use.
    """

    ticket_id: str
    session_id: str
    token_type: TokenType
    tool_name: str
    content_digest: str
    created_at: float = field(default_factory=time.time)
    ttl_seconds: float = 60.0
    status: TicketStatus = TicketStatus.ISSUED
    bound_credential_handles: list[str] = field(default_factory=list)

    @property
    def expires_at(self) -> float:
        """Expiration timestamp."""
        return self.created_at + self.ttl_seconds

    @property
    def is_expired(self) -> bool:
        """Check if ticket TTL has elapsed."""
        return time.time() > self.expires_at

    @property
    def is_active(self) -> bool:
        """Check if ticket can be consumed."""
        return self.status == TicketStatus.ISSUED and not self.is_expired
