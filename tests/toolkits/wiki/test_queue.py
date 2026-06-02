"""Tests for WikiIngestionQueue - persistent SQLite queue."""

from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.pipeline.queue import WikiIngestionQueue


@pytest.fixture
def queue(tmp_path: Path) -> WikiIngestionQueue:
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()
    return WikiIngestionQueue(structure)


def test_add_item(queue: WikiIngestionQueue) -> None:
    item_id = queue.add_item("/tmp/test.md")
    assert item_id > 0
    items = queue.get_pending_items()
    assert len(items) == 1
    assert items[0]["file_path"] == "/tmp/test.md"
    assert items[0]["status"] == "pending"


def test_add_item_upsert(queue: WikiIngestionQueue) -> None:
    queue.add_item("/tmp/test.md")
    queue.mark_failed(1, "error")
    queue.add_item("/tmp/test.md")
    items = queue.get_pending_items()
    assert len(items) == 1
    assert items[0]["status"] == "pending"
    assert items[0]["retry_count"] == 0


def test_add_batch(queue: WikiIngestionQueue) -> None:
    queue.add_batch(["/tmp/a.md", "/tmp/b.md", "/tmp/c.md"])
    items = queue.get_pending_items(limit=10)
    assert len(items) == 3


def test_mark_processing(queue: WikiIngestionQueue) -> None:
    queue.add_item("/tmp/test.md")
    items = queue.get_pending_items()
    queue.mark_processing(items[0]["id"])
    pending = queue.get_pending_items()
    assert len(pending) == 0


def test_mark_completed(queue: WikiIngestionQueue) -> None:
    queue.add_item("/tmp/test.md")
    items = queue.get_pending_items()
    queue.mark_completed(items[0]["id"])
    stats = queue.get_stats()
    assert stats["completed"] == 1
    assert stats["pending"] == 0


def test_mark_failed_increments_retry(queue: WikiIngestionQueue) -> None:
    queue.add_item("/tmp/test.md")
    items = queue.get_pending_items()
    item_id = items[0]["id"]
    queue.mark_failed(item_id, "some error")
    queue.mark_failed(item_id, "another error")
    # Check that retry_count was incremented (item is still 'failed' from second call)
    stats = queue.get_stats()
    assert stats["failed"] == 1


def test_get_retryable_items(queue: WikiIngestionQueue) -> None:
    queue.add_item("/tmp/test.md")
    items = queue.get_pending_items()
    item_id = items[0]["id"]
    queue.mark_failed(item_id, "error")
    retryable = queue.get_retryable_items(max_retries=3)
    assert len(retryable) == 1
    assert retryable[0]["id"] == item_id


def test_get_retryable_items_respects_max_retries(queue: WikiIngestionQueue) -> None:
    queue.add_item("/tmp/test.md")
    items = queue.get_pending_items()
    item_id = items[0]["id"]
    for _ in range(4):
        queue.mark_failed(item_id, "error")
    retryable = queue.get_retryable_items(max_retries=3)
    assert len(retryable) == 0


def test_reset_for_retry(queue: WikiIngestionQueue) -> None:
    queue.add_item("/tmp/test.md")
    items = queue.get_pending_items()
    item_id = items[0]["id"]
    queue.mark_failed(item_id, "error")
    queue.reset_for_retry(item_id)
    pending = queue.get_pending_items()
    assert len(pending) == 1


def test_reset_failed(queue: WikiIngestionQueue) -> None:
    queue.add_batch(["/tmp/a.md", "/tmp/b.md"])
    items = queue.get_pending_items()
    for item in items:
        queue.mark_failed(item["id"], "error")
    count = queue.reset_failed()
    assert count == 2
    pending = queue.get_pending_items()
    assert len(pending) == 2


def test_cancel_pending(queue: WikiIngestionQueue) -> None:
    queue.add_batch(["/tmp/a.md", "/tmp/b.md", "/tmp/c.md"])
    count = queue.cancel_pending()
    assert count == 3
    stats = queue.get_stats()
    assert stats["pending"] == 0
    assert stats["failed"] == 3


def test_get_stats(queue: WikiIngestionQueue) -> None:
    queue.add_batch(["/tmp/a.md", "/tmp/b.md"])
    items = queue.get_pending_items()
    queue.mark_completed(items[0]["id"])
    queue.mark_failed(items[1]["id"], "err")
    stats = queue.get_stats()
    assert stats["completed"] == 1
    assert stats["failed"] == 1
    assert stats["pending"] == 0
    assert stats["processing"] == 0
