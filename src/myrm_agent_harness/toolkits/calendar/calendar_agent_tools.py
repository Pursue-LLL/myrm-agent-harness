"""Agent tools for calendar event management.

Single ``calendar_manage`` tool with multi-action interface.

[INPUT]
- .types::CalendarEvent (POS: Calendar domain types.)
- .protocols::CalendarStore (POS: Protocols for the calendar toolkit.)

[OUTPUT]
- create_calendar_tools: Create calendar management tools bound to a store.

[POS]
Agent tools for calendar event management.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Literal

from langchain_core.tools import BaseTool, tool

from myrm_agent_harness.toolkits.calendar.types import CalendarEvent
from myrm_agent_harness.utils.logger_utils import get_agent_logger

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.calendar.protocols import CalendarStore

logger = get_agent_logger(__name__)


def create_calendar_tools(
    store: CalendarStore,
    *,
    agent_id: str | None = None,
) -> list[BaseTool]:
    """Create calendar management tools.

    Args:
        store: Calendar persistence store.
        agent_id: Agent ID for event attribution.

    Returns:
        List of calendar tools.
    """

    @tool("calendar_manage_tool")
    async def calendar_manage(
        action: Literal[
            "create_event",
            "list_events",
            "get_event",
            "update_event",
            "delete_event",
        ],
        # Event params
        event_id: str = "",
        title: str = "",
        description: str = "",
        location: str = "",
        start_at: str = "",
        end_at: str = "",
        all_day: bool = False,
        rrule: str = "",
        color: str = "",
        reminder_minutes: int = 0,
        status: str = "confirmed",
        # Filter params
        date_from: str = "",
        date_to: str = "",
        status_filter: str = "",
        limit: int = 20,
    ) -> str:
        """Manage calendar events. Create, list, update, or delete events.

        Args:
            action: The operation to perform.
            event_id: Event ID (for get/update/delete).
            title: Event title (for create/update).
            description: Event description.
            location: Event location.
            start_at: Start time in ISO 8601 format (e.g. "2026-05-15T10:00:00Z").
            end_at: End time in ISO 8601 format.
            all_day: Whether this is an all-day event.
            rrule: RFC 5545 recurrence rule (e.g. "FREQ=WEEKLY;BYDAY=MO,WE,FR").
            color: Hex color for display (e.g. "#4F46E5").
            reminder_minutes: Minutes before event to remind (0 = no reminder).
            status: Event status: "confirmed", "tentative", "cancelled".
            date_from: Filter events starting after this ISO 8601 time.
            date_to: Filter events starting before this ISO 8601 time.
            status_filter: Filter by status.
            limit: Max events to return (for list_events).

        Returns:
            JSON string with operation result.
        """
        import json

        try:
            if action == "create_event":
                if not title:
                    return json.dumps({"error": "title is required"})
                if not start_at:
                    return json.dumps({"error": "start_at is required"})

                event = CalendarEvent(
                    event_id=uuid.uuid4().hex[:32],
                    title=title,
                    description=description,
                    location=location or None,
                    start_at=datetime.fromisoformat(start_at.replace("Z", "+00:00")),
                    end_at=datetime.fromisoformat(end_at.replace("Z", "+00:00")) if end_at else None,
                    all_day=all_day,
                    rrule=rrule or None,
                    color=color or None,
                    source="agent",
                    agent_id=agent_id,
                    reminder_minutes=reminder_minutes or None,
                    status=status,
                )
                saved = await store.save_event(event)
                return json.dumps({
                    "status": "created",
                    "event_id": saved.event_id,
                    "title": saved.title,
                    "start_at": saved.start_at.isoformat() if saved.start_at else None,
                })

            elif action == "list_events":
                start = datetime.fromisoformat(date_from.replace("Z", "+00:00")) if date_from else None
                end = datetime.fromisoformat(date_to.replace("Z", "+00:00")) if date_to else None
                sf = status_filter if status_filter else None

                events = await store.list_events(
                    start=start, end=end, status=sf, limit=limit
                )
                total = await store.count_events(start=start, end=end, status=sf)

                return json.dumps({
                    "total": total,
                    "events": [
                        {
                            "event_id": e.event_id,
                            "title": e.title,
                            "start_at": e.start_at.isoformat() if e.start_at else None,
                            "end_at": e.end_at.isoformat() if e.end_at else None,
                            "status": e.status,
                            "location": e.location,
                        }
                        for e in events
                    ],
                })

            elif action == "get_event":
                if not event_id:
                    return json.dumps({"error": "event_id is required"})
                event = await store.get_event(event_id)
                if not event:
                    return json.dumps({"error": f"Event {event_id} not found"})
                return json.dumps({
                    "event_id": event.event_id,
                    "title": event.title,
                    "description": event.description,
                    "location": event.location,
                    "start_at": event.start_at.isoformat() if event.start_at else None,
                    "end_at": event.end_at.isoformat() if event.end_at else None,
                    "all_day": event.all_day,
                    "rrule": event.rrule,
                    "status": event.status,
                    "reminder_minutes": event.reminder_minutes,
                })

            elif action == "update_event":
                if not event_id:
                    return json.dumps({"error": "event_id is required"})
                existing = await store.get_event(event_id)
                if not existing:
                    return json.dumps({"error": f"Event {event_id} not found"})

                if title:
                    existing.title = title
                if description:
                    existing.description = description
                if location:
                    existing.location = location
                if start_at:
                    existing.start_at = datetime.fromisoformat(start_at.replace("Z", "+00:00"))
                if end_at:
                    existing.end_at = datetime.fromisoformat(end_at.replace("Z", "+00:00"))
                if rrule:
                    existing.rrule = rrule
                if color:
                    existing.color = color
                if reminder_minutes:
                    existing.reminder_minutes = reminder_minutes
                if status:
                    existing.status = status

                saved = await store.save_event(existing)
                return json.dumps({
                    "status": "updated",
                    "event_id": saved.event_id,
                    "title": saved.title,
                })

            elif action == "delete_event":
                if not event_id:
                    return json.dumps({"error": "event_id is required"})
                deleted = await store.delete_event(event_id)
                if not deleted:
                    return json.dumps({"error": f"Event {event_id} not found"})
                return json.dumps({"status": "deleted", "event_id": event_id})

            else:
                return json.dumps({"error": f"Unknown action: {action}"})

        except Exception as e:
            logger.warning("Calendar tool error: %s", e)
            return json.dumps({"error": str(e)})

    @tool("find_optimal_meeting_slots_tool")
    async def find_optimal_meeting_slots(
        attendees: list[str],
        duration_minutes: int,
        date_start: str,
        date_end: str,
    ) -> str:
        """Find optimal available meeting slots for a group of attendees.

        Queries the underlying calendar free/busy data (respecting user privacy)
        and computes mutual free time slots using an interval tree engine.

        Args:
            attendees: List of user identifiers to invite (e.g. open_ids, emails).
            duration_minutes: Duration of the meeting in minutes.
            date_start: Start boundary in ISO 8601 format (e.g. "2026-05-15T00:00:00Z").
            date_end: End boundary in ISO 8601 format.

        Returns:
            JSON string with recommended time slots rendered as interactive cards.
        """
        import json

        from myrm_agent_harness.toolkits.calendar.free_busy_engine import FreeBusyEngine, TimeSlot

        try:
            start = datetime.fromisoformat(date_start.replace("Z", "+00:00"))
            end = datetime.fromisoformat(date_end.replace("Z", "+00:00"))

            # 1. Fetch free/busy state (delegated to provider which handles OAuth safely)
            # We don't fetch meeting details, only busy boolean states.
            busy_data = await store.get_free_busy(attendees, start, end)

            # 2. Extract busy slots from the response
            all_busy_slots: list[TimeSlot] = []
            for user_data in busy_data:
                slots = user_data.get("busy_slots", [])
                for slot in slots:
                    bs_start = datetime.fromisoformat(slot["start"].replace("Z", "+00:00"))
                    bs_end = datetime.fromisoformat(slot["end"].replace("Z", "+00:00"))
                    all_busy_slots.append(TimeSlot(start=bs_start, end=bs_end))

            # 3. Find optimal free slots via the algorithmic engine
            free_slots = FreeBusyEngine.find_free_slots(
                all_busy_slots,
                search_start=start,
                search_end=end,
                duration_minutes=duration_minutes
            )

            # 4. Limit to top 3 optimal slots for frontend rendering
            recommended = free_slots[:3]

            if not recommended:
                return json.dumps({
                    "status": "no_slots_found",
                    "message": "No common free time found in the specified range."
                })

            formatted_slots = [
                {
                    "start": s.start.isoformat(),
                    "end": (s.start + timedelta(minutes=duration_minutes)).isoformat(),
                    "duration_minutes": duration_minutes,
                }
                for s in recommended
            ]

            data_str = json.dumps({
                "status": "success",
                "slots": formatted_slots,
                "attendees": attendees,
            }).replace("'", "&#39;")

            return f"<timeslotpicker data='{data_str}'></timeslotpicker>"

        except Exception as e:
            logger.warning("Calendar find slots tool error: %s", e)
            return json.dumps({"error": str(e)})

    return [calendar_manage, find_optimal_meeting_slots]
