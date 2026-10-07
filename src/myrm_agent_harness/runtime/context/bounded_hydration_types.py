"""Types and data models for bounded initial page loading and upward cursor hydration.

Defines wire formats, lightweight stubs, heavy tool payload references,
and sliding window in-memory eviction structures.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- MessageHydrationState: Hydration state of a message item within the client/runtime memory window.
- HeavyToolBlobReference: Metadata pointer referencing a detached heavy tool output stored in blob store.
- HydratedMessageItem: A message item inside the active hydration window with optional detached payloads.
- LightweightMessageStub: Evicted lightweight stub retaining only structural identification and preview.
- BoundedInitialPageHeader: Initial fast-load page payload for instant session opening (<100ms).
- UpwardPageSlice: Paginated upward historical slice loaded on demand during upward scrolling.

[POS]
Types and data models for bounded initial page loading and upward cursor hydration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class MessageHydrationState(StrEnum):
    """Hydration state of a message item within the client/runtime memory window."""

    FULL = "full"
    EVICTED_STUB = "evicted_stub"
    BLOB_DETACHED = "blob_detached"


@dataclass(frozen=True)
class HeavyToolBlobReference:
    """Metadata pointer referencing a detached heavy tool output stored in blob store."""

    blob_id: str
    original_size_bytes: int
    content_preview: str
    content_type: str = "text/plain"
    timestamp: float = 0.0


@dataclass(frozen=True)
class HydratedMessageItem:
    """A message item inside the active hydration window with optional detached payloads."""

    message_id: str
    session_id: str
    role: str
    content: str
    created_at: float
    hydration_state: MessageHydrationState = MessageHydrationState.FULL
    tool_blobs: tuple[HeavyToolBlobReference, ...] = ()
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class LightweightMessageStub:
    """Evicted lightweight stub retaining only structural identification and preview."""

    message_id: str
    session_id: str
    role: str
    preview: str
    created_at: float
    original_length: int
    hydration_state: MessageHydrationState = MessageHydrationState.EVICTED_STUB


@dataclass(frozen=True)
class BoundedInitialPageHeader:
    """Initial fast-load page payload for instant session opening (<100ms)."""

    session_id: str
    total_messages_count: int
    page_size: int
    has_earlier_messages: bool
    earliest_cursor_id: str | None
    messages: tuple[HydratedMessageItem, ...]


@dataclass(frozen=True)
class UpwardPageSlice:
    """Paginated upward historical slice loaded on demand during upward scrolling."""

    session_id: str
    messages: tuple[HydratedMessageItem, ...]
    has_more_earlier: bool
    next_upward_cursor: str | None
