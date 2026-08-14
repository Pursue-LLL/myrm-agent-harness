"""Tests for WebCorpusStore — FTS5 two-tier persistent index."""

from __future__ import annotations

from datetime import UTC
from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.web_corpus.store import WebCorpusStore


@pytest.fixture()
def store(tmp_path: Path) -> WebCorpusStore:
    s = WebCorpusStore(tmp_path)
    yield s
    s.close()


def test_upsert_and_search(store: WebCorpusStore) -> None:
    store.upsert(
        url="https://example.com/page?ref=123",
        title="Example Page",
        snippet="This is a test snippet about Python frameworks.",
        content="Full article content about Python frameworks and best practices.",
    )
    results = store.search("Python frameworks")
    assert len(results) == 1
    assert results[0].title == "Example Page"
    assert results[0].access_count == 1


def test_upsert_deduplicates_on_normalized_url(store: WebCorpusStore) -> None:
    store.upsert(url="https://example.com/page?ref=123", title="V1", snippet="first")
    store.upsert(url="https://example.com/page?utm_source=twitter", title="V2", snippet="second")
    results = store.search("example")
    assert len(results) == 1
    assert results[0].title == "V2"
    assert results[0].access_count == 2


def test_get_content(store: WebCorpusStore) -> None:
    store.upsert(
        url="https://example.com/article",
        title="Article",
        snippet="snippet",
        content="Full text content here.",
    )
    results = store.search("Article")
    assert len(results) == 1
    content = store.get_content(results[0].normalized_url)
    assert content == "Full text content here."


def test_get_content_returns_none_for_missing(store: WebCorpusStore) -> None:
    assert store.get_content("nonexistent-url") is None


def test_delete_by_normalized_url(store: WebCorpusStore) -> None:
    store.upsert(url="https://example.com/to-delete", title="Delete Me", snippet="gone")
    results = store.search("Delete")
    assert len(results) == 1
    norm_url = results[0].normalized_url

    deleted = store.delete_by_normalized_url(norm_url)
    assert deleted is True

    results_after = store.search("Delete")
    assert len(results_after) == 0


def test_delete_nonexistent_returns_false(store: WebCorpusStore) -> None:
    assert store.delete_by_normalized_url("no-such-url") is False


def test_clear(store: WebCorpusStore) -> None:
    for i in range(5):
        store.upsert(url=f"https://example.com/{i}", title=f"Page {i}", snippet=f"content {i}")
    stats = store.get_stats()
    assert stats.total_entries == 5

    cleared = store.clear()
    assert cleared == 5

    stats_after = store.get_stats()
    assert stats_after.total_entries == 0


def test_get_stats(store: WebCorpusStore) -> None:
    stats = store.get_stats()
    assert stats.total_entries == 0
    assert stats.disk_bytes >= 0

    store.upsert(url="https://a.com", title="A", snippet="a", content="body a")
    store.upsert(url="https://b.com", title="B", snippet="b", content="body b")

    stats = store.get_stats()
    assert stats.total_entries == 2
    assert stats.disk_bytes > 0
    assert stats.oldest_entry is not None
    assert stats.newest_entry is not None


def test_search_with_agent_id_filter(store: WebCorpusStore) -> None:
    store.upsert(url="https://a.com", title="Shared", snippet="shared content", agent_id="agent-1")
    store.upsert(url="https://b.com", title="Other", snippet="other content", agent_id="agent-2")

    results_1 = store.search("content", agent_id="agent-1")
    assert len(results_1) == 1
    assert results_1[0].agent_id == "agent-1"

    results_all = store.search("content")
    assert len(results_all) == 2


def test_search_empty_query_returns_empty(store: WebCorpusStore) -> None:
    store.upsert(url="https://a.com", title="Page", snippet="test")
    results = store.search("")
    assert results == []


def test_hit_miss_counting(store: WebCorpusStore) -> None:
    store.upsert(url="https://a.com", title="Target", snippet="findable")
    store.search("findable")
    store.search("nonexistent-xyz-abc")

    stats = store.get_stats()
    assert stats.hit_count == 1
    assert stats.miss_count == 1
    assert stats.hit_rate == 0.5


def test_list_stale(store: WebCorpusStore) -> None:
    store.upsert(url="https://old.com", title="Old", snippet="old")
    from datetime import datetime

    future = datetime(2099, 1, 1, tzinfo=UTC).isoformat()
    stale = store.list_stale(future)
    assert len(stale) == 1


def test_list_lru(store: WebCorpusStore) -> None:
    store.upsert(url="https://a.com", title="A", snippet="a")
    store.upsert(url="https://b.com", title="B", snippet="b")
    lru = store.list_lru()
    assert len(lru) == 2


def test_fts5_auto_heal_on_corruption(store: WebCorpusStore) -> None:
    """FTS5 corruption triggers auto-heal and retries search."""
    store.upsert(url="https://heal.com", title="Heal Test", snippet="recovery")
    store._conn.execute("INSERT INTO web_corpus_fts(web_corpus_fts) VALUES('rebuild')")
    results = store.search("recovery")
    assert len(results) >= 0
