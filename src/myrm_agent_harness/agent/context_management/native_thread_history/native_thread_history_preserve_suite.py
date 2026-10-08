"""Suite implementing large native thread history preservation with sort key fallback guard.

[INPUT]
- agent.context_management.native_thread_history.sort_key_fallback_guard::GuardValidationResult,
  SortKeyFallbackGuard (POS: Sort key validation and graceful fallback guard for thread history retrieval.)
- agent.context_management.native_thread_history.thread_history_types::FallbackStatus, SortKeyKind,
  ThreadEntry, ThreadHistoryPage, ThreadPageRequest (POS: Strongly typed contracts for large native thread
  history and sort key fallback.)

[OUTPUT]
- LargeNativeThreadHistoryPreserveSuite: Industrial-grade suite for large native thread history preservation.

[POS]
Suite implementing large native thread history preservation with sort key fallback guard.
"""

from __future__ import annotations

import base64
import json
from typing import Callable

from .sort_key_fallback_guard import GuardValidationResult, SortKeyFallbackGuard
from .thread_history_types import (
    FallbackStatus,
    SortKeyKind,
    ThreadEntry,
    ThreadHistoryPage,
    ThreadPageRequest,
)


class LargeNativeThreadHistoryPreserveSuite:
    """Industrial-grade suite for large native thread history preservation."""

    def __init__(self, guard: SortKeyFallbackGuard | None = None) -> None:
        """Initialize the history preservation suite."""
        self._guard: SortKeyFallbackGuard = guard or SortKeyFallbackGuard()
        self._threads: dict[str, list[ThreadEntry]] = {}

    def record_entry(self, entry: ThreadEntry) -> None:
        """Append an atomic thread entry into internal thread registry."""
        if entry.thread_id not in self._threads:
            self._threads[entry.thread_id] = []
        self._threads[entry.thread_id].append(entry)

    def record_entries(self, entries: list[ThreadEntry]) -> None:
        """Batch append atomic thread entries."""
        for entry in entries:
            self.record_entry(entry)

    def get_thread_count(self, thread_id: str) -> int:
        """Return total number of entries recorded for a given thread."""
        return len(self._threads.get(thread_id, []))

    def fetch_thread_page(self, request: ThreadPageRequest) -> ThreadHistoryPage:
        """Fetch a paginated slice of thread history guarded against sort key crashes."""
        guard_result: GuardValidationResult = self._guard.evaluate_request(request)

        # Fallback condition 1: Unsupported key yields empty page fallback
        if guard_result.fallback_status == FallbackStatus.FALLBACK_EMPTY_PAGE:
            return ThreadHistoryPage(
                thread_id=request.thread_id,
                entries=[],
                total_entries=0,
                has_more=False,
                next_cursor=None,
                fallback_applied=True,
                fallback_status=FallbackStatus.FALLBACK_EMPTY_PAGE,
                fallback_reason=guard_result.fallback_reason,
                retained_byte_size=0,
            )

        entries = list(self._threads.get(request.thread_id, []))
        total_entries = len(entries)
        effective_key = guard_result.effective_sort_key or SortKeyKind.SECTION_POSITION.value

        # Sort entries stably based on resolved key
        entries.sort(key=self._resolve_sort_comparator(effective_key))

        # Decode cursor if present
        start_offset = 0
        if request.cursor:
            start_offset = self._decode_cursor(request.cursor)
            if start_offset < 0 or start_offset > total_entries:
                start_offset = 0

        # Apply pagination slice
        page_size = max(1, request.page_size)
        candidate_slice = entries[start_offset : start_offset + page_size]

        # Apply byte-budget preservation ceiling
        retained_entries: list[ThreadEntry] = []
        cumulative_bytes = 0
        for item in candidate_slice:
            if cumulative_bytes + item.byte_size > request.max_retained_bytes and retained_entries:
                break
            retained_entries.append(item)
            cumulative_bytes += item.byte_size

        end_offset = start_offset + len(retained_entries)
        has_more = end_offset < total_entries
        next_cursor = self._encode_cursor(end_offset) if has_more else None

        return ThreadHistoryPage(
            thread_id=request.thread_id,
            entries=retained_entries,
            total_entries=total_entries,
            has_more=has_more,
            next_cursor=next_cursor,
            fallback_applied=guard_result.fallback_applied,
            fallback_status=guard_result.fallback_status,
            fallback_reason=guard_result.fallback_reason,
            retained_byte_size=cumulative_bytes,
        )

    def _resolve_sort_comparator(
        self, sort_key: str
    ) -> Callable[[ThreadEntry], tuple[int, int]]:
        """Resolve a robust composite sort key avoiding TypeError on None values."""
        if sort_key == SortKeyKind.SECTION_POSITION.value:
            # Sort by section_position (None sorted last at 999_999_999), then by sequence
            return lambda item: (
                item.section_position if item.section_position is not None else 999_999_999,
                item.sequence,
            )
        if sort_key == SortKeyKind.CREATED_AT.value:
            return lambda item: (item.created_at_epoch_ms, item.sequence)
        # Default to sequence
        return lambda item: (item.sequence, 0)

    @staticmethod
    def _encode_cursor(offset: int) -> str:
        """Encode pagination offset as a base64 opaque cursor token."""
        payload = json.dumps({"offset": offset})
        return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("utf-8")

    @staticmethod
    def _decode_cursor(cursor_str: str) -> int:
        """Decode base64 opaque cursor token to integer offset."""
        try:
            raw = base64.urlsafe_b64decode(cursor_str.encode("utf-8")).decode("utf-8")
            data = json.loads(raw)
            if isinstance(data, dict) and "offset" in data and isinstance(data["offset"], int):
                return data["offset"]
        except Exception:
            pass
        return 0
