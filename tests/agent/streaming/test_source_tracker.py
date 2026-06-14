"""Tests for SourceTracker — session-level source deduplication and indexing.

Covers:
- URL-based deduplication
- Content-hash-based deduplication (non-URL sources)
- Global index assignment
- Incremental return (add_batch returns only new items)
- extract_and_add from metadata
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.streaming.source_tracker import SourceTracker


class TestSourceTrackerDedup:
    """URL and content-based deduplication."""

    def test_url_dedup(self) -> None:
        tracker = SourceTracker()
        batch1 = tracker.add_batch([
            {"url": "https://a.com", "title": "A"},
            {"url": "https://b.com", "title": "B"},
        ])
        assert len(batch1) == 2

        batch2 = tracker.add_batch([
            {"url": "https://a.com", "title": "A duplicate"},
        ])
        assert len(batch2) == 0
        assert len(tracker.all_sources) == 2

    def test_content_hash_dedup_for_non_url_sources(self) -> None:
        tracker = SourceTracker()
        batch1 = tracker.add_batch([
            {"type": "mcp", "skill_name": "web_search"},
        ])
        assert len(batch1) == 1

        batch2 = tracker.add_batch([
            {"type": "mcp", "skill_name": "web_search"},
        ])
        assert len(batch2) == 0

    def test_different_content_not_deduped(self) -> None:
        tracker = SourceTracker()
        batch = tracker.add_batch([
            {"type": "mcp", "skill_name": "web_search"},
            {"type": "mcp", "skill_name": "code_exec"},
        ])
        assert len(batch) == 2


class TestSourceTrackerIndex:
    """Global index assignment."""

    def test_sequential_index(self) -> None:
        tracker = SourceTracker()
        batch = tracker.add_batch([
            {"url": "https://a.com"},
            {"url": "https://b.com"},
            {"url": "https://c.com"},
        ])
        assert [s["index"] for s in batch] == [1, 2, 3]

    def test_index_persists_across_batches(self) -> None:
        tracker = SourceTracker()
        tracker.add_batch([{"url": "https://a.com"}])
        batch2 = tracker.add_batch([{"url": "https://b.com"}])
        assert batch2[0]["index"] == 2

    def test_deduped_items_dont_consume_index(self) -> None:
        tracker = SourceTracker()
        tracker.add_batch([{"url": "https://a.com"}])
        tracker.add_batch([{"url": "https://a.com"}])  # dedup
        batch3 = tracker.add_batch([{"url": "https://b.com"}])
        assert batch3[0]["index"] == 2  # not 3


class TestSourceTrackerIncremental:
    """add_batch returns only new items."""

    def test_incremental_return(self) -> None:
        tracker = SourceTracker()
        batch1 = tracker.add_batch([
            {"url": "https://a.com"},
            {"url": "https://b.com"},
        ])
        assert len(batch1) == 2

        batch2 = tracker.add_batch([
            {"url": "https://a.com"},
            {"url": "https://c.com"},
        ])
        assert len(batch2) == 1
        assert batch2[0]["url"] == "https://c.com"

    def test_all_sources_accumulates(self) -> None:
        tracker = SourceTracker()
        tracker.add_batch([{"url": "https://a.com"}])
        tracker.add_batch([{"url": "https://b.com"}])
        assert len(tracker.all_sources) == 2


class TestSourceTrackerExtract:
    """extract_and_add from metadata dict."""

    def test_extract_from_metadata(self) -> None:
        tracker = SourceTracker()
        metadata = {"sources": [{"url": "https://x.com", "title": "X"}]}
        new_items = tracker.extract_and_add(metadata)
        assert len(new_items) == 1
        assert new_items[0]["index"] == 1

    def test_extract_empty_sources(self) -> None:
        tracker = SourceTracker()
        assert tracker.extract_and_add({"sources": []}) == []
        assert tracker.extract_and_add({}) == []
        assert tracker.extract_and_add({"sources": None}) == []

    def test_non_dict_items_skipped(self) -> None:
        tracker = SourceTracker()
        batch = tracker.add_batch(["not_a_dict", 42, None, {"url": "https://a.com"}])
        assert len(batch) == 1


class TestSourceTrackerAllSourcesCopy:
    """all_sources returns a copy, not a reference."""

    def test_copy_isolation(self) -> None:
        tracker = SourceTracker()
        tracker.add_batch([{"url": "https://a.com"}])
        sources = tracker.all_sources
        sources.clear()
        assert len(tracker.all_sources) == 1


class TestSourceTrackerEdgeCases:
    """Edge cases and robustness."""

    def test_empty_batch(self) -> None:
        tracker = SourceTracker()
        result = tracker.add_batch([])
        assert result == []
        assert tracker.all_sources == []

    def test_url_with_fragment_not_deduped(self) -> None:
        """URLs with different fragments are treated as different."""
        tracker = SourceTracker()
        batch = tracker.add_batch([
            {"url": "https://a.com/page#section1"},
            {"url": "https://a.com/page#section2"},
        ])
        assert len(batch) == 2

    def test_mixed_url_and_non_url_sources(self) -> None:
        tracker = SourceTracker()
        batch = tracker.add_batch([
            {"url": "https://a.com"},
            {"type": "mcp", "skill_name": "web_search"},
            {"type": "conversation_history", "title": "Chat 1"},
            {"url": "https://b.com"},
        ])
        assert len(batch) == 4
        assert [s["index"] for s in batch] == [1, 2, 3, 4]

    def test_large_batch_performance(self) -> None:
        """Verify no performance degradation with larger batches."""
        tracker = SourceTracker()
        sources = [{"url": f"https://example{i}.com"} for i in range(100)]
        batch = tracker.add_batch(sources)
        assert len(batch) == 100
        assert batch[-1]["index"] == 100

    def test_source_preserves_original_fields(self) -> None:
        tracker = SourceTracker()
        batch = tracker.add_batch([
            {"url": "https://a.com", "title": "Test", "snippet": "Some text", "extra_field": 42},
        ])
        assert batch[0]["title"] == "Test"
        assert batch[0]["snippet"] == "Some text"
        assert batch[0]["extra_field"] == 42
        assert batch[0]["index"] == 1

    def test_index_field_in_input_ignored_for_dedup(self) -> None:
        """Input index field should not affect content-hash dedup."""
        tracker = SourceTracker()
        batch1 = tracker.add_batch([{"type": "mcp", "skill_name": "test", "index": 99}])
        assert len(batch1) == 1
        assert batch1[0]["index"] == 1  # overwritten by tracker

        batch2 = tracker.add_batch([{"type": "mcp", "skill_name": "test", "index": 100}])
        assert len(batch2) == 0  # deduped (index excluded from hash)
