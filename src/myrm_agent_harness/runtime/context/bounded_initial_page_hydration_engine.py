"""Bounded initial page hydration engine with lazy upward cursor paging and memory eviction.

Enables instant session opening (<100ms) on ultra-long conversations via bounded
latest-turn hydration, demand-driven upward pagination, and sliding window stubbing.

[INPUT]
- runtime.context.bounded_hydration_types::BoundedInitialPageHeader, HeavyToolBlobReference,
  HydratedMessageItem, LightweightMessageStub, MessageHydrationState, UpwardPageSlice (POS: Types and data
  models for bounded initial page loading and upward cursor hydration.)
- runtime.context.heavy_tool_payload_blob_store::HeavyToolPayloadBlobStore (POS: Heavy tool payload blob
  store and detachment manager.)

[OUTPUT]
- BoundedInitialPageHydrationEngine: Manages bounded initial hydration, lazy upward cursor paging, and
  sliding window eviction.

[POS]
Bounded initial page hydration engine with lazy upward cursor paging and memory eviction.
"""

from __future__ import annotations

import time

from myrm_agent_harness.runtime.context.bounded_hydration_types import (
    BoundedInitialPageHeader,
    HeavyToolBlobReference,
    HydratedMessageItem,
    LightweightMessageStub,
    MessageHydrationState,
    UpwardPageSlice,
)
from myrm_agent_harness.runtime.context.heavy_tool_payload_blob_store import (
    HeavyToolPayloadBlobStore,
)


class BoundedInitialPageHydrationEngine:
    """Manages bounded initial hydration, lazy upward cursor paging, and sliding window eviction."""

    def __init__(
        self,
        blob_store: HeavyToolPayloadBlobStore | None = None,
        default_page_size: int = 20,
        max_window_size: int = 100,
    ) -> None:
        self._blob_store = blob_store or HeavyToolPayloadBlobStore()
        self._default_page_size = max(default_page_size, 5)
        self._max_window_size = max(max_window_size, 20)
        # Canonical timeline storage: session_id -> list of raw message dicts
        self._raw_messages: dict[str, list[dict[str, str | float]]] = {}
        # Active hydrated in-memory state: session_id -> message_id -> HydratedMessageItem | LightweightMessageStub
        self._active_window: dict[str, dict[str, HydratedMessageItem | LightweightMessageStub]] = {}

    def append_raw_message(
        self,
        session_id: str,
        message_id: str,
        role: str,
        content: str,
        created_at: float | None = None,
    ) -> HydratedMessageItem:
        """Append a message to the canonical session timeline, automatically detaching heavy payloads."""
        timestamp = created_at if created_at is not None else time.time()
        self._raw_messages.setdefault(session_id, []).append(
            {
                "message_id": message_id,
                "role": role,
                "content": content,
                "created_at": timestamp,
            }
        )

        # Detect and isolate oversize payload
        preview, blob_ref = self._blob_store.detect_and_detach_payload(content)
        blobs: tuple[HeavyToolBlobReference, ...] = (blob_ref,) if blob_ref else ()
        state = (
            MessageHydrationState.BLOB_DETACHED
            if blob_ref
            else MessageHydrationState.FULL
        )

        item = HydratedMessageItem(
            message_id=message_id,
            session_id=session_id,
            role=role,
            content=preview,
            created_at=timestamp,
            hydration_state=state,
            tool_blobs=blobs,
            metadata={},
        )

        session_window = self._active_window.setdefault(session_id, {})
        session_window[message_id] = item
        return item

    def load_bounded_initial_page(
        self, session_id: str, page_size: int | None = None
    ) -> BoundedInitialPageHeader:
        """Instantly load only the latest bounded page for ultra-fast session opening (<100ms)."""
        limit = page_size if page_size is not None else self._default_page_size
        raw_list = self._raw_messages.get(session_id, [])
        total_count = len(raw_list)

        if total_count == 0:
            return BoundedInitialPageHeader(
                session_id=session_id,
                total_messages_count=0,
                page_size=limit,
                has_earlier_messages=False,
                earliest_cursor_id=None,
                messages=(),
            )

        # Slice latest N items
        start_idx = max(total_count - limit, 0)
        sliced_raw = raw_list[start_idx:]
        has_earlier = start_idx > 0
        earliest_cursor = sliced_raw[0]["message_id"] if has_earlier else None

        items: list[HydratedMessageItem] = []
        for raw in sliced_raw:
            msg_id = str(raw["message_id"])
            item = self._hydrate_single_item(
                session_id, msg_id, str(raw["role"]), str(raw["content"]), float(raw["created_at"])
            )
            items.append(item)

        return BoundedInitialPageHeader(
            session_id=session_id,
            total_messages_count=total_count,
            page_size=limit,
            has_earlier_messages=has_earlier,
            earliest_cursor_id=str(earliest_cursor) if earliest_cursor else None,
            messages=tuple(items),
        )

    def hydrate_upward_page(
        self,
        session_id: str,
        before_cursor_id: str,
        limit: int | None = None,
    ) -> UpwardPageSlice:
        """Fetch historical messages chronologically preceding before_cursor_id on user upward scroll."""
        page_limit = limit if limit is not None else self._default_page_size
        raw_list = self._raw_messages.get(session_id, [])

        cursor_idx = -1
        for idx, item in enumerate(raw_list):
            if item["message_id"] == before_cursor_id:
                cursor_idx = idx
                break

        if cursor_idx <= 0:
            return UpwardPageSlice(
                session_id=session_id,
                messages=(),
                has_more_earlier=False,
                next_upward_cursor=None,
            )

        start_idx = max(cursor_idx - page_limit, 0)
        sliced_raw = raw_list[start_idx:cursor_idx]
        has_more_earlier = start_idx > 0
        next_cursor = sliced_raw[0]["message_id"] if has_more_earlier else None

        items: list[HydratedMessageItem] = []
        for raw in sliced_raw:
            msg_id = str(raw["message_id"])
            item = self._hydrate_single_item(
                session_id, msg_id, str(raw["role"]), str(raw["content"]), float(raw["created_at"])
            )
            items.append(item)

        return UpwardPageSlice(
            session_id=session_id,
            messages=tuple(items),
            has_more_earlier=has_more_earlier,
            next_upward_cursor=str(next_cursor) if next_cursor else None,
        )

    def evict_sliding_window_stubs(self, session_id: str) -> int:
        """Evict oldest hydrated messages into lightweight stubs when exceeding window capacity."""
        session_window = self._active_window.get(session_id, {})
        if len(session_window) <= self._max_window_size:
            return 0

        # Evict oldest hydrated full items first
        excess_count = len(session_window) - self._max_window_size
        evicted = 0

        # Sort items chronologically
        items_sorted = sorted(
            session_window.items(), key=lambda kv: kv[1].created_at
        )

        for msg_id, item in items_sorted:
            if evicted >= excess_count:
                break
            if isinstance(item, HydratedMessageItem):
                stub = LightweightMessageStub(
                    message_id=item.message_id,
                    session_id=item.session_id,
                    role=item.role,
                    preview=item.content[:60],
                    created_at=item.created_at,
                    original_length=len(item.content),
                )
                session_window[msg_id] = stub
                evicted += 1

        return evicted

    def rehydrate_stub(
        self, session_id: str, message_id: str
    ) -> HydratedMessageItem | None:
        """Rehydrate an evicted lightweight stub back to full message item on demand."""
        raw_list = self._raw_messages.get(session_id, [])
        for raw in raw_list:
            if raw["message_id"] == message_id:
                return self._hydrate_single_item(
                    session_id,
                    message_id,
                    str(raw["role"]),
                    str(raw["content"]),
                    float(raw["created_at"]),
                )
        return None

    def fork_aligned_slice(
        self,
        session_id: str,
        up_to_message_id: str,
        new_session_id: str,
    ) -> tuple[HydratedMessageItem, ...]:
        """Align and fork canonical conversation history up to up_to_message_id into a new session."""
        raw_list = self._raw_messages.get(session_id, [])
        target_idx = -1
        for idx, item in enumerate(raw_list):
            if item["message_id"] == up_to_message_id:
                target_idx = idx
                break

        if target_idx == -1:
            return ()

        forked_raw = raw_list[: target_idx + 1]
        forked_items: list[HydratedMessageItem] = []

        for raw in forked_raw:
            item = self.append_raw_message(
                session_id=new_session_id,
                message_id=str(raw["message_id"]),
                role=str(raw["role"]),
                content=str(raw["content"]),
                created_at=float(raw["created_at"]),
            )
            forked_items.append(item)

        return tuple(forked_items)

    def _hydrate_single_item(
        self,
        session_id: str,
        message_id: str,
        role: str,
        content: str,
        created_at: float,
    ) -> HydratedMessageItem:
        """Helper to construct hydrated item with heavy payload detachment."""
        preview, blob_ref = self._blob_store.detect_and_detach_payload(content)
        blobs: tuple[HeavyToolBlobReference, ...] = (blob_ref,) if blob_ref else ()
        state = (
            MessageHydrationState.BLOB_DETACHED
            if blob_ref
            else MessageHydrationState.FULL
        )

        item = HydratedMessageItem(
            message_id=message_id,
            session_id=session_id,
            role=role,
            content=preview,
            created_at=created_at,
            hydration_state=state,
            tool_blobs=blobs,
            metadata={},
        )
        self._active_window.setdefault(session_id, {})[message_id] = item
        return item
