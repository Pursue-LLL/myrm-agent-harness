"""Calendar toolkit for agent event management.

Provides calendar event CRUD operations as LangChain tools,
following the same Protocol-based dependency injection pattern as the kanban toolkit.
"""

from myrm_agent_harness.toolkits.calendar.calendar_agent_tools import create_calendar_tools
from myrm_agent_harness.toolkits.calendar.protocols import CalendarStore
from myrm_agent_harness.toolkits.calendar.stores import InMemoryCalendarStore
from myrm_agent_harness.toolkits.calendar.types import CalendarEvent

__all__ = [
    "CalendarEvent",
    "CalendarStore",
    "InMemoryCalendarStore",
    "create_calendar_tools",
]
