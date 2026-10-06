"""Type definitions for file-move tracking session store.

Provides data structures for path-bound stable ChatIds, move event logs,
session message entries, and lightweight metadata snapshots.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ChatMessageEntry:
    """An immutable conversation message appended to session JSONL."""

    entry_id: str
    role: str
    content: str
    timestamp: float
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ChatMetaSnapshot:
    """Lightweight metadata snapshot for fast session indexing without full log parsing."""

    chat_id: str
    bound_path: str
    title: str
    message_count: int
    created_at: float
    last_active_at: float
    path_history: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class FileMoveEvent:
    """Event representing a file or directory rename/move."""

    old_path: str
    new_path: str
    timestamp: float
    is_directory: bool = False


@dataclass(frozen=True)
class FileTrackResolution:
    """Result of resolving a file path to its stable ChatId."""

    chat_id: str
    bound_path: str
    is_newly_created: bool
    matched_via_history: bool
