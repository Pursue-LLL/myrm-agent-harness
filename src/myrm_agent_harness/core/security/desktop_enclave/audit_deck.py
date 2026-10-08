"""Desktop Action Audit Deck and Live Intent HUD telemetry ring buffer.

[INPUT]
- DesktopActionAuditRecord, CriticalDesktopAction

[OUTPUT]
- DesktopActionAuditDeck: ring buffer store for action telemetry, replay, and live intent streaming.

[POS]
- Harness core security subsystem for Computer-Use safe enclaves.
"""

from __future__ import annotations

import threading
import time
from collections import deque

from myrm_agent_harness.core.security.desktop_enclave.types import (
    CriticalDesktopAction,
    DesktopActionAuditRecord,
)


class DesktopActionAuditDeck:
    """Thread-safe ring buffer for desktop action auditing and replay."""

    def __init__(self, capacity: int = 1000) -> None:
        if capacity <= 0:
            raise ValueError("Audit deck capacity must be positive")
        self._capacity = capacity
        self._records: deque[DesktopActionAuditRecord] = deque(maxlen=capacity)
        self._lock = threading.Lock()

    @property
    def capacity(self) -> int:
        """Maximum number of records retained in memory."""
        return self._capacity

    def record_action(
        self,
        record_id: str,
        action: CriticalDesktopAction,
        enclave_verified: bool,
        executed: bool,
        execution_latency_ms: float,
        status: str,
    ) -> DesktopActionAuditRecord:
        """Record an evaluated or executed desktop action."""
        record = DesktopActionAuditRecord(
            record_id=record_id,
            action=action,
            enclave_verified=enclave_verified,
            executed=executed,
            execution_latency_ms=execution_latency_ms,
            status=status,
            recorded_at=time.time(),
        )
        with self._lock:
            self._records.append(record)
        return record

    def list_records(self, limit: int = 100) -> list[DesktopActionAuditRecord]:
        """Return the most recent audit records in reverse chronological order."""
        with self._lock:
            records = list(self._records)
        records.reverse()
        return records[:limit]

    def get_record(self, record_id: str) -> DesktopActionAuditRecord | None:
        """Retrieve a specific audit record by record_id."""
        with self._lock:
            for rec in self._records:
                if rec.record_id == record_id:
                    return rec
        return None

    def get_live_intent_feed(self, limit: int = 20) -> list[dict[str, str | float | bool]]:
        """Return lightweight HUD projection for live agent action monitoring."""
        records = self.list_records(limit=limit)
        feed: list[dict[str, str | float | bool]] = []
        for r in records:
            feed.append(
                {
                    "record_id": r.record_id,
                    "action_id": r.action.action_id,
                    "action_type": str(r.action.action_type),
                    "semantic_intent": r.action.semantic_intent,
                    "risk_level": str(r.action.risk_level),
                    "enclave_verified": r.enclave_verified,
                    "executed": r.executed,
                    "status": r.status,
                    "execution_latency_ms": r.execution_latency_ms,
                    "recorded_at": r.recorded_at,
                }
            )
        return feed

    def clear(self) -> None:
        """Clear all audit records in memory."""
        with self._lock:
            self._records.clear()
