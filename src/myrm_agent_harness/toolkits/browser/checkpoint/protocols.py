"""Browser checkpoint protocols.


[INPUT]
- typing::Protocol (POS: Python protocol type)
- .thread_models::ThreadRecord (POS: thread record data model)

[OUTPUT]
- ThreadStoreProtocol: thread store protocol (defines unified interface for thread registry)

[POS]
Browser checkpoint thread storage protocol. Defines unified interface for thread registration, update, query, and deletion.
Supports multiple backend implementations (SQLite/PostgreSQL), following the framework's Protocol-first principle.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from .thread_models import ThreadRecord


@runtime_checkable
class ThreadStoreProtocol(Protocol):
    """Thread registry storage protocol.

    Defines the unified interface for checkpoint thread tracking.
    Implementations may use SQLite (single-instance) or PostgreSQL (multi-instance).

    Thread lifecycle:
    1. register() -> creates entry with status="active"
    2. update_core_fields() -> updates last_active_at + auto-increments checkpoint_count
    3. update_metadata() -> updates last_url + session_domain (throttled)
    4. mark_completed() / mark_failed() -> sets final status
    5. find_active_threads() -> returns all threads with status="active"

    Dual-speed update design:
    - Core fields (last_active_at, checkpoint_count): always updated
    - Metadata fields (last_url, session_domain): throttled for efficiency
    """

    async def setup(self) -> None:
        """Create checkpoint_threads table if not exists."""
        ...

    async def register(self, thread_id: str) -> None:
        """Register a new active thread.

        Args:
            thread_id: Thread ID to register
        """
        ...

    async def update_core_fields(self, thread_id: str) -> None:
        """Update core fields (last_active_at + checkpoint_count increment).

        Called on every checkpoint to track activity and count.

        Args:
            thread_id: Thread ID to update
        """
        ...

    async def update_metadata(
        self,
        thread_id: str,
        last_url: str | None = None,
        session_domain: str | None = None,
    ) -> None:
        """Update metadata fields (last_url + session_domain).

        Throttled update: only updates if 60s elapsed since last update.

        Args:
            thread_id: Thread ID to update
            last_url: Last visited URL (optional)
            session_domain: SessionVault domain (optional)
        """
        ...

    async def mark_completed(self, thread_id: str) -> None:
        """Mark thread as completed.

        Args:
            thread_id: Thread ID to mark as completed
        """
        ...

    async def mark_failed(self, thread_id: str, error_message: str) -> None:
        """Mark thread as failed with error message.

        Args:
            thread_id: Thread ID to mark as failed
            error_message: Error message describing the failure
        """
        ...

    async def find_active_threads(self, max_age_hours: float | None = None) -> list[ThreadRecord]:
        """Find all active threads.

        Args:
            max_age_hours: Optional age filter (only return threads active within N hours).
                         None means return all active threads.

        Returns:
            List of active thread records

        """
        ...

    async def get_thread(self, thread_id: str) -> ThreadRecord | None:
        """Get thread record by ID.

        Args:
            thread_id: Thread ID to retrieve

        Returns:
            Thread record if exists, None otherwise
        """
        ...

    async def delete_thread(self, thread_id: str) -> bool:
        """Delete thread record.

        Args:
            thread_id: Thread ID to delete

        Returns:
            True if deleted, False if not found
        """
        ...

    async def cleanup_old_threads(self, days: int = 7) -> int:
        """Delete completed/failed threads older than threshold.

        Args:
            days: Age threshold in days

        Returns:
            Number of deleted threads
        """
        ...

    async def get_stats(self) -> dict[str, int]:
        """Get registry statistics.

        Returns:
            Dict with counts: active, completed, failed, total
        """
        ...
