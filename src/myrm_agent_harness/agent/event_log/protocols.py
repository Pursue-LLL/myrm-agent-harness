"""EventLogBackend — 5th framework protocol.

Sits alongside SandboxExecutor, StorageProvider, SkillBackend, and
Checkpointer as a dependency-injected capability.

[INPUT]

[OUTPUT]
- EventLogBackend: runtime_checkable Protocol

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

    async def get_all_session_ids(self) -> list[str]:
        """Retrieve all session IDs in the backend."""
        ...

    async def close(self) -> None:
        """Flush pending writes and release resources."""
        ...
