"""Protocols and interfaces for spend governance and tamper-evident ledger.

[INPUT]
- None (pure standard library typing)

[OUTPUT]
- SpendRecordDTO: Read-only data transfer object for spend records
- SpendLedgerProtocol: Protocol defining append-only tamper-evident ledger operations

[POS]
Harness-level pure protocol for spend governance. Implemented by server-side persistence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class SpendRecordDTO:
    """Immutable data transfer object representing an audited spend event."""

    session_id: str
    agent_id: str
    tool_name: str
    amount: float
    currency: str
    action_digest: str
    previous_hash: str
    record_hmac: str
    created_at_iso: str
    description: str = ""


@runtime_checkable
class SpendLedgerProtocol(Protocol):
    """Protocol for tamper-evident append-only spend record ledger."""

    async def record_spend(
        self,
        *,
        session_id: str,
        agent_id: str,
        tool_name: str,
        amount: float,
        currency: str,
        action_digest: str,
        description: str = "",
    ) -> SpendRecordDTO:
        """Append an audited spend record to the HMAC-chained ledger."""
        ...

    async def verify_chain(self, session_id: str) -> tuple[bool, str]:
        """Verify the cryptographic integrity of the session ledger.

        Returns:
            (is_valid, detail_message)
        """
        ...

    async def get_session_spent(self, session_id: str, currency: str = "USD") -> float:
        """Calculate the total accumulated spend for the session."""
        ...
