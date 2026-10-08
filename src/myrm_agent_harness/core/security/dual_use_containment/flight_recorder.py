"""Security flight recorder and tamper-evident audit ledger.

Maintains append-only in-memory logs of dual-use skill evaluations, HITL approvals,
and artifact exfiltration inspection events for forensic traceability.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field


@dataclass
class FlightRecorderEntry:
    """An immutable record capturing a single security evaluation or enforcement action."""

    entry_id: str
    event_type: str  # "skill_gate_evaluation", "artifact_egress_shield", "hitl_approval_granted"
    subject: str
    decision: str  # "permitted", "blocked", "requires_hitl"
    details: dict[str, str | int | float | bool] = field(default_factory=dict)
    timestamp: str = ""


class SecurityFlightRecorder:
    """Append-only audit flight recorder."""

    def __init__(self, max_capacity: int = 1000) -> None:
        self.max_capacity = max_capacity
        self._ledger: list[FlightRecorderEntry] = []

    def record_event(
        self,
        entry_id: str,
        event_type: str,
        subject: str,
        decision: str,
        details: dict[str, str | int | float | bool] | None = None,
    ) -> FlightRecorderEntry:
        """Append an immutable audit event to the flight recorder ledger."""
        now_iso = datetime.datetime.now(datetime.UTC).isoformat()
        entry = FlightRecorderEntry(
            entry_id=entry_id,
            event_type=event_type,
            subject=subject,
            decision=decision,
            details=details or {},
            timestamp=now_iso,
        )
        self._ledger.append(entry)

        if len(self._ledger) > self.max_capacity:
            self._ledger = self._ledger[-self.max_capacity :]

        return entry

    def get_recent_entries(self, limit: int = 50) -> list[FlightRecorderEntry]:
        """Fetch the most recent flight recorder entries in reverse chronological order."""
        return list(reversed(self._ledger[-limit:]))
