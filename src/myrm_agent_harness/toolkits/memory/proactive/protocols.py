"""Commitment store protocol — persistence boundary for commitment records.

[INPUT]
- commitment.types::{CommitmentRecord, CommitmentStatus} (POS: type definitions)

[OUTPUT]
- CommitmentStore: Protocol for commitment persistence backends.

[POS]
Protocol-only module. Defines the persistence contract that server-layer
implementations (SQLite, PostgreSQL, etc.) must satisfy.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from myrm_agent_harness.toolkits.memory.proactive.types import (
    CommitmentRecord,
    CommitmentStatus,
)


@runtime_checkable
class CommitmentStore(Protocol):
    """Persistence contract for commitment records.

    Implementations live in the Server layer; only the protocol is
    defined here so the Harness stays business-agnostic.
    """

    async def upsert(self, record: CommitmentRecord) -> CommitmentRecord:
        """Insert or update (by dedupe_key within scope) a commitment."""
        ...

    async def list_pending(
        self,
        *,
        agent_id: str,
        user_id: str,
        now_ms: int,
        limit: int = 20,
    ) -> list[CommitmentRecord]:
        """List active commitments (pending + unsnoozed) for a scope."""
        ...

    async def list_due(
        self,
        *,
        agent_id: str,
        user_id: str,
        now_ms: int,
        limit: int = 3,
    ) -> list[CommitmentRecord]:
        """List commitments whose due window has arrived."""
        ...

    async def mark_status(
        self,
        ids: list[str],
        status: CommitmentStatus,
        now_ms: int,
    ) -> int:
        """Transition commitments to a terminal status. Returns count updated."""
        ...

    async def mark_attempted(self, ids: list[str], now_ms: int) -> int:
        """Increment attempt counter. Returns count updated."""
        ...

    async def snooze(self, commitment_id: str, until_ms: int, now_ms: int) -> bool:
        """Snooze a commitment until a future time. Returns True if updated."""
        ...

    async def count_sent_rolling(
        self,
        *,
        agent_id: str,
        user_id: str,
        since_ms: int,
    ) -> int:
        """Count commitments sent within a rolling window (for daily limits)."""
        ...

    async def expire_stale(
        self,
        now_ms: int,
        expire_after_ms: int,
        *,
        agent_id: str | None = None,
        user_id: str | None = None,
    ) -> int:
        """Expire commitments past their latest + grace period. Returns count."""
        ...

    async def list_all(
        self,
        *,
        user_id: str,
        status: CommitmentStatus | None = None,
        agent_id: str | None = None,
        limit: int = 100,
    ) -> list[CommitmentRecord]:
        """List all commitments for a user with optional filters."""
        ...
