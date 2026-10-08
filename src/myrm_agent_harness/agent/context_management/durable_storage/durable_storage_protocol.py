"""Unified interface protocol for all durable storage backends.

[INPUT]
- CommitWrite: Atomic batch write specification.
- ConversationRecord: Conversation domain model.
- DocumentRecord: Versioned document domain model.
- EntryRecord: Transcript entry domain model.
- StorageBackendKind: Backend classification enum.
- TaskRecord: Task execution domain model.

[OUTPUT]
- DurableStorageProtocol: Abstract base contract implemented identically by Memory, JSONL, and SQLite backends.

[POS]
Uniform storage contract ensuring seamless swappability across local, desktop, and cloud sandbox deployments.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Sequence

from .durable_storage_types import (
    CommitWrite,
    ConversationRecord,
    DocumentRecord,
    EntryRecord,
    StorageBackendKind,
    TaskRecord,
)


class DurableStorageProtocol(ABC):
    """Uniform contract governing all durable persistence backends."""

    @property
    @abstractmethod
    def backend_kind(self) -> StorageBackendKind:
        """Return the category identifier of the storage backend."""
        ...

    @abstractmethod
    def commit(self, writes: Sequence[CommitWrite]) -> int:
        """Atomically persist a batch of writes under a newly advanced sequence number.

        Args:
            writes: Ordered sequence of atomic mutation directives.

        Returns:
            int: The advanced monotonic sequence number (seq) assigned to this commit.
        """
        ...

    @abstractmethod
    def get_conversation(self, conversation_id: str) -> ConversationRecord | None:
        """Retrieve a conversation descriptor by its unique ID."""
        ...

    @abstractmethod
    def get_entry(self, entry_id: str) -> EntryRecord | None:
        """Retrieve an entry by its unique entry ID."""
        ...

    @abstractmethod
    def list_entries(
        self,
        conversation_id: str,
        limit: int = 100,
        after_seq: int = 0,
    ) -> Sequence[EntryRecord]:
        """Fetch chronologically ordered entries for a conversation after a given sequence number."""
        ...

    @abstractmethod
    def get_task(self, task_id: str) -> TaskRecord | None:
        """Retrieve a task execution state by task ID."""
        ...

    @abstractmethod
    def get_document(self, document_id: str) -> DocumentRecord | None:
        """Retrieve a versioned document by document ID."""
        ...

    @abstractmethod
    def get_current_seq(self) -> int:
        """Return the highest monotonically committed sequence number."""
        ...

    @abstractmethod
    def reopen(self) -> None:
        """Simulate or execute closing and re-opening storage, restoring state from disk/log."""
        ...

    @abstractmethod
    def close(self) -> None:
        """Flush pending buffers, perform final checkpoints, and release locks."""
        ...
