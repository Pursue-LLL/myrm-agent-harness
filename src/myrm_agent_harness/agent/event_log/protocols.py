"""EventLogBackend — 5th framework protocol.

Sits alongside SandboxExecutor, StorageProvider, SkillBackend, and
Checkpointer as a dependency-injected capability.

[INPUT]

[OUTPUT]
- EventLogBackend: runtime_checkable Protocol
- FlushableEventLogBackend: runtime_checkable Protocol

[POS]
Protocol contract. Framework provides FileEventLogBackend;
business layer may extend with SQLite / PostgreSQL implementations.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .types import EventFilter, StructuredEvent


@runtime_checkable
class EventLogBackend(Protocol):
    """Append-only event store protocol."""

    async def append(self, events: list[StructuredEvent]) -> None:
        """Persist a batch of events. Must be idempotent on duplicate sequences."""
        ...

    async def get_events(self, session_id: str, event_filter: EventFilter | None = None) -> list[StructuredEvent]:
        """Retrieve events for a session, optionally filtered."""
        ...

    async def get_latest_custom_state(
        self, session_id: str, custom_type: str | None = None
    ) -> dict[str, object]:
        """Retrieve the latest consolidated custom state for a session.

        If custom_type is specified, returns that extension's state dictionary.
        If custom_type is None, returns a dict mapping all custom_types to their latest state.
        """
        ...

    async def get_all_session_ids(self) -> list[str]:
        """Retrieve all session IDs in the backend."""
        ...

    async def close(self) -> None:
        """Flush pending writes and release resources."""
        ...


@runtime_checkable
class FlushableEventLogBackend(Protocol):
    """Event log backend that supports explicit in-flight flush barriers."""

    async def flush(self) -> None:
        """Flush pending writes and enforce durability barrier."""
        ...
