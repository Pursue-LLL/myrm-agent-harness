"""Calendar domain types.

[INPUT]
- (none)

[OUTPUT]
- CalendarEvent: Domain type for calendar events.

[POS]
Calendar domain types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class CalendarEvent:
    """Calendar event domain type."""

    event_id: str
    title: str
    description: str = ""
    location: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    all_day: bool = False
    rrule: str | None = None
    color: str | None = None
    source: str = "manual"
    agent_id: str | None = None
    chat_id: str | None = None
    reminder_minutes: int | None = None
    status: str = "confirmed"
    created_at: datetime | None = None
    updated_at: datetime | None = None
    metadata: dict[str, str] = field(default_factory=dict)
