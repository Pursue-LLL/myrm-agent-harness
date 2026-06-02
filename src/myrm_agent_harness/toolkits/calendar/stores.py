"""In-memory CalendarStore implementation.

Used for testing and as a reference for persistence adapters.

[INPUT]
- .types::CalendarEvent (POS: Calendar domain types.)
- .protocols::CalendarStore (POS: Protocols for the calendar toolkit.)

[OUTPUT]
- InMemoryCalendarStore: Non-persistent reference implementation.

[POS]
In-memory CalendarStore implementation.
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime

from myrm_agent_harness.toolkits.calendar.protocols import CalendarStore
from myrm_agent_harness.toolkits.calendar.types import CalendarEvent


class InMemoryCalendarStore(CalendarStore):
    """Non-persistent reference implementation.

    Thread-safety: not guaranteed — intended for single-process tests.
    Production deployments must use a database-backed implementation.
    """

    def __init__(self) -> None:
        self._events: dict[str, CalendarEvent] = {}

    async def get_event(self, event_id: str) -> CalendarEvent | None:
        event = self._events.get(event_id)
        return copy.deepcopy(event) if event else None

    async def list_events(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[CalendarEvent]:
        results = list(self._events.values())
        if start is not None:
            results = [e for e in results if e.start_at and e.start_at >= start]
        if end is not None:
            results = [e for e in results if e.start_at and e.start_at <= end]
        if status is not None:
            results = [e for e in results if e.status == status]
        results.sort(key=lambda e: e.start_at or datetime.min.replace(tzinfo=UTC))
        results = results[offset:]
        if limit is not None:
            results = results[:limit]
        return [copy.deepcopy(e) for e in results]

    async def count_events(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        status: str | None = None,
    ) -> int:
        count = 0
        for e in self._events.values():
            if start is not None and (not e.start_at or e.start_at < start):
                continue
            if end is not None and (not e.start_at or e.start_at > end):
                continue
            if status is not None and e.status != status:
                continue
            count += 1
        return count

    async def save_event(self, event: CalendarEvent) -> CalendarEvent:
        event.updated_at = datetime.now(UTC)
        if event.created_at is None:
            event.created_at = datetime.now(UTC)
        self._events[event.event_id] = copy.deepcopy(event)
        return event

    async def delete_event(self, event_id: str) -> bool:
        if event_id not in self._events:
            return False
        del self._events[event_id]
        return True

    async def get_free_busy(
        self,
        user_ids: list[str],
        start: datetime,
        end: datetime,
        **kwargs: object,
    ) -> list[dict[str, object]]:
        all_results = []
        for uid in user_ids:
            busy_slots = []
            for e in self._events.values():
                if e.status != "confirmed":
                    continue
                if e.start_at and e.end_at and e.start_at < end and e.end_at > start:
                    busy_slots.append({"start": e.start_at.isoformat(), "end": e.end_at.isoformat()})
            all_results.append({"user_id": uid, "busy_slots": busy_slots})
        return all_results
