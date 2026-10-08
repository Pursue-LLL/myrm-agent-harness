# [INPUT]: EventAuditRecord, EventEnvelopePayload, Sequence
# [OUTPUT]: EventAuditTrailManager
# [POS]: agent/context_management/event_cache_preservation/event_audit_trail_manager.py

"""Event audit trail manager decoupling high-frequency raw events from user conversation windows.

[INPUT]
- EventAuditRecord, EventEnvelopePayload: Contract models.
- Sequence: Typing.

[OUTPUT]
- EventAuditTrailManager: Records event trails and selectively promotes critical alerts to human UI.

[POS]
Audit and UI isolation layer in event cache preservation subsystem keeping chat windows clutter-free.
"""

from __future__ import annotations

import uuid
from typing import Sequence

from .event_envelope_types import (
    EventAuditRecord,
    EventEnvelopePayload,
)


class EventAuditTrailManager:
    """Stores high-frequency event history in an audit stream without polluting the main conversation."""

    def __init__(self, max_audit_entries: int = 1000) -> None:
        self._audit_records: list[EventAuditRecord] = []
        self._max_audit_entries = max_audit_entries

    def record_event(
        self,
        event: EventEnvelopePayload,
        summary: str = "",
        force_promote_to_user: bool = False,
    ) -> EventAuditRecord:
        """Record an event into the audit trail and evaluate if it should be displayed to the human."""
        # Critical and high-priority events or explicit promotions are surfaced to user
        should_promote = force_promote_to_user or (event.priority in ("critical", "high"))

        rec = EventAuditRecord(
            audit_id=f"audit-{uuid.uuid4().hex[:8]}",
            event_id=event.event_id,
            source=event.source,
            timestamp_iso=event.timestamp_iso,
            summary=summary or f"Received {event.source.value} event: {event.event_id}",
            was_promoted_to_user=should_promote,
            details_dump=event.payload_text,
        )

        self._audit_records.append(rec)
        if len(self._audit_records) > self._max_audit_entries:
            self._audit_records.pop(0)

        return rec

    def list_audit_trail(
        self,
        only_promoted: bool = False,
        limit: int = 50,
    ) -> Sequence[EventAuditRecord]:
        """Query audit records, optionally filtering only user-promoted items."""
        records = [
            r for r in self._audit_records
            if not only_promoted or r.was_promoted_to_user
        ]
        return tuple(records[-limit:])
