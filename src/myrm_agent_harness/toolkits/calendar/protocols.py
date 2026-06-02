"""Protocols for the calendar toolkit.

Defines the persistence contract that the application layer must satisfy.

[INPUT]
- .types::CalendarEvent (POS: Calendar domain types.)

[OUTPUT]
- CalendarStore: Persistence contract for calendar events.

[POS]
Protocols for the calendar toolkit.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.calendar.types import CalendarEvent


@runtime_checkable
class CalendarStore(Protocol):
    """Persistence contract for calendar events.

    All datetime values are UTC. Authorization is handled by the
    service layer — the store itself is auth-agnostic.
    """

    async def get_event(self, event_id: str) -> CalendarEvent | None:
        """Return an event by ID, or None."""
        ...

    async def list_events(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[CalendarEvent]:
        """Return events with optional time range and status filters."""
        ...

    async def count_events(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        status: str | None = None,
    ) -> int:
        """Count events matching filters."""
        ...

    async def save_event(self, event: CalendarEvent) -> CalendarEvent:
        """Create or update an event (upsert)."""
        ...

    async def delete_event(self, event_id: str) -> bool:
        """Delete an event. Returns True if deleted."""
        ...

    async def get_free_busy(
        self,
        user_ids: list[str],
        start: datetime,
        end: datetime,
        **kwargs: object,
    ) -> list[dict[str, object]]:
        """Return free/busy information for a list of users.

        Args:
            user_ids: List of user identifiers.
            start: Start time.
            end: End time.
            **kwargs: Additional provider-specific arguments (e.g. auth tokens).

        Returns:
            List of dicts with 'user_id' and a list of 'busy_slots' (start, end).
        """
        ...
