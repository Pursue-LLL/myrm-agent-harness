# calendar/

## Overview
Calendar toolkit — event management for agent. Provides calendar event CRUD operations as LangChain tools via Protocol-based dependency injection.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Calendar toolkit public API. | — |
| calendar_agent_tools.py | Core | Agent-callable tools for calendar event management. | ✅ |
| free_busy_engine.py | Core | Free/busy time slot calculation engine. | ✅ |
| protocols.py | Core | CalendarStore protocol — storage interface for calendar events. | ✅ |
| stores.py | Core | In-memory and local file implementations of CalendarStore. | ✅ |
| types.py | Config | Calendar event data models. | ✅ |

## Key Dependencies

- `utils` (files)
