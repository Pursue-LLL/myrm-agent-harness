"""Tests for large native thread history preserve suite and sort key fallback guard."""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management.native_thread_history import (
    FallbackStatus,
    LargeNativeThreadHistoryPreserveSuite,
    SortKeyFallbackGuard,
    SortKeyKind,
    ThreadEntry,
    ThreadPageRequest,
)


_UNSET_POSITION = -999_999


def _make_dummy_entry(
    thread_id: str,
    index: int,
    section_position: int | None = _UNSET_POSITION,
    byte_size: int = 100,
) -> ThreadEntry:
    resolved_position = index * 10 if section_position == _UNSET_POSITION else section_position
    return ThreadEntry(
        entry_id=f"entry_{thread_id}_{index}",
        thread_id=thread_id,
        section_position=resolved_position,
        sequence=index,
        content=f"Thread content chunk #{index} for {thread_id}",
        byte_size=byte_size,
        created_at_epoch_ms=1728000000000 + index * 1000,
        metadata={"idx": str(index)},
    )


def test_large_thread_history_pagination_and_byte_retention() -> None:
    """Test pagination through large native thread history and byte ceiling enforcement."""
    suite = LargeNativeThreadHistoryPreserveSuite()
    thread_id = "thread_alpha"

    # Insert 15 entries, each 200 bytes
    entries = [_make_dummy_entry(thread_id, i, byte_size=200) for i in range(15)]
    suite.record_entries(entries)

    assert suite.get_thread_count(thread_id) == 15

    # Request first page of 5 items with plenty of byte budget
    req_page1 = ThreadPageRequest(
        thread_id=thread_id,
        sort_key=SortKeyKind.SECTION_POSITION.value,
        page_size=5,
        max_retained_bytes=10_000,
    )
    page1 = suite.fetch_thread_page(req_page1)

    assert len(page1.entries) == 5
    assert page1.total_entries == 15
    assert page1.has_more is True
    assert page1.next_cursor is not None
    assert page1.fallback_applied is False
    assert page1.retained_byte_size == 1000

    # Request second page using cursor
    req_page2 = ThreadPageRequest(
        thread_id=thread_id,
        sort_key=SortKeyKind.SECTION_POSITION.value,
        page_size=5,
        cursor=page1.next_cursor,
        max_retained_bytes=10_000,
    )
    page2 = suite.fetch_thread_page(req_page2)
    assert len(page2.entries) == 5
    assert page2.entries[0].sequence == 5
    assert page2.has_more is True

    # Test byte budget truncation: page size is 5 (1000 bytes needed), but budget is only 500 bytes (fits 2)
    req_budget_limited = ThreadPageRequest(
        thread_id=thread_id,
        page_size=5,
        max_retained_bytes=500,
    )
    page_budget = suite.fetch_thread_page(req_budget_limited)
    assert len(page_budget.entries) == 2
    assert page_budget.retained_byte_size == 400


def test_unsupported_sort_key_empty_page_fallback_guard() -> None:
    """Test unsupported sort key triggers graceful empty page fallback instead of crashing."""
    # Storage only supports 'sequence'
    restricted_guard = SortKeyFallbackGuard(supported_keys={"sequence"})
    suite = LargeNativeThreadHistoryPreserveSuite(guard=restricted_guard)
    thread_id = "thread_beta"

    suite.record_entries([_make_dummy_entry(thread_id, i) for i in range(10)])

    # Query requesting 'section_position' which is NOT supported by restricted guard
    req = ThreadPageRequest(
        thread_id=thread_id,
        sort_key="section_position",
        allow_natural_fallback=False,
    )
    page = suite.fetch_thread_page(req)

    # Must return a valid empty page without raising unhandled exception
    assert page.fallback_applied is True
    assert page.fallback_status == FallbackStatus.FALLBACK_EMPTY_PAGE
    assert page.entries == []
    assert page.total_entries == 0
    assert page.has_more is False
    assert page.next_cursor is None
    assert page.fallback_reason is not None
    assert "unsupported by the storage backend" in page.fallback_reason


def test_section_position_sorting_with_missing_positions() -> None:
    """Test stable sorting when some entries have section_position=None without TypeError."""
    suite = LargeNativeThreadHistoryPreserveSuite()
    thread_id = "thread_gamma"

    # Create entries with mixed section_position: 0, None, 20, None, 10
    e0 = _make_dummy_entry(thread_id, 0, section_position=0)
    e1_none = _make_dummy_entry(thread_id, 1, section_position=None)
    e2 = _make_dummy_entry(thread_id, 2, section_position=20)
    e3_none = _make_dummy_entry(thread_id, 3, section_position=None)
    e4 = _make_dummy_entry(thread_id, 4, section_position=10)

    suite.record_entries([e0, e1_none, e2, e3_none, e4])

    req = ThreadPageRequest(
        thread_id=thread_id,
        sort_key=SortKeyKind.SECTION_POSITION.value,
        page_size=10,
    )
    page = suite.fetch_thread_page(req)

    assert len(page.entries) == 5
    # section_position order: 0 -> 10 -> 20 -> None(seq 1) -> None(seq 3)
    assert page.entries[0].sequence == 0
    assert page.entries[1].sequence == 4  # section_position 10
    assert page.entries[2].sequence == 2  # section_position 20
    assert page.entries[3].sequence == 1  # None sorted last
    assert page.entries[4].sequence == 3  # None sorted last
    assert page.fallback_applied is False


def test_natural_key_fallback_and_cursor_resilience() -> None:
    """Test graceful fallback to natural sequence key when enabled, with cursor continuity."""
    restricted_guard = SortKeyFallbackGuard(supported_keys={"sequence"})
    suite = LargeNativeThreadHistoryPreserveSuite(guard=restricted_guard)
    thread_id = "thread_delta"

    suite.record_entries([_make_dummy_entry(thread_id, i) for i in range(8)])

    # Request unsupported sort key, but allow natural fallback
    req = ThreadPageRequest(
        thread_id=thread_id,
        sort_key="section_position",
        page_size=4,
        allow_natural_fallback=True,
    )
    page1 = suite.fetch_thread_page(req)

    assert page1.fallback_applied is True
    assert page1.fallback_status == FallbackStatus.FALLBACK_NATURAL_KEY
    assert len(page1.entries) == 4
    assert page1.entries[0].sequence == 0
    assert page1.has_more is True

    # Follow up with second page
    req2 = ThreadPageRequest(
        thread_id=thread_id,
        sort_key="section_position",
        page_size=4,
        cursor=page1.next_cursor,
        allow_natural_fallback=True,
    )
    page2 = suite.fetch_thread_page(req2)
    assert len(page2.entries) == 4
    assert page2.entries[0].sequence == 4
    assert page2.has_more is False
