"""Permanent-failure notification deduplication ledger.

[INPUT]
delivery_id: str — unique delivery identifier

[OUTPUT]
- PermanentFailureNotificationLedger: Protocol defining persistent notify dedup
- InMemoryPermanentFailureNotificationLedger: In-memory implementation for testing

[POS]
Prevents duplicate on_permanent_failure callbacks across process restarts.
DLQ checks this ledger before invoking the callback; marks after success.
"""

from __future__ import annotations

from typing import Protocol


class PermanentFailureNotificationLedger(Protocol):
    """Protocol for persistent deduplication of permanent-failure notifications."""

    def was_notified(self, delivery_id: str) -> bool:
        """Return True if this delivery's permanent-failure was already notified."""
        ...

    def mark_notified(self, delivery_id: str) -> None:
        """Record that permanent-failure notification was sent for this delivery."""
        ...


class InMemoryPermanentFailureNotificationLedger:
    """In-memory implementation suitable for testing and single-process use."""

    def __init__(self) -> None:
        self._notified: set[str] = set()

    def was_notified(self, delivery_id: str) -> bool:
        return delivery_id in self._notified

    def mark_notified(self, delivery_id: str) -> None:
        self._notified.add(delivery_id)
