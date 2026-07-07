"""Persistent dedupe ledger for permanent-failure user notifications.

[INPUT]
- (none — protocol + optional in-memory implementation for tests)

[OUTPUT]
- PermanentFailureNotificationLedger: Protocol for delivery_id notify dedupe
- InMemoryPermanentFailureNotificationLedger: Process-local test double

[POS]
Generic hook for business/server layers to persist DLQ permanent-failure alerts
across process restarts without coupling harness to Myrm-specific storage.
"""

from __future__ import annotations

from typing import Protocol


class PermanentFailureNotificationLedger(Protocol):
    """Tracks delivery IDs that already triggered permanent-failure notification."""

    def was_notified(self, delivery_id: str) -> bool:
        """Return True when permanent-failure notification was already emitted."""
        ...

    def mark_notified(self, delivery_id: str) -> None:
        """Record that permanent-failure notification was emitted for delivery_id."""
        ...


class InMemoryPermanentFailureNotificationLedger:
    """In-memory ledger for unit tests (not durable across restarts)."""

    __slots__ = ("_notified_ids",)

    def __init__(self) -> None:
        self._notified_ids: set[str] = set()

    def was_notified(self, delivery_id: str) -> bool:
        return delivery_id in self._notified_ids

    def mark_notified(self, delivery_id: str) -> None:
        self._notified_ids.add(delivery_id)
