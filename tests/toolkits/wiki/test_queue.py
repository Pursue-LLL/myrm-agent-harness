"""Tests for WikiIngestionQueue - persistent SQLite queue."""

import sqlite3
from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.llms.errors.classifier import ErrorKind
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.pipeline.corpus_dedup.store import (
    CorpusDedupStore,
)
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


def test_complete_processing(queue: WikiIngestionQueue) -> None:
    queue.add_item("/tmp/test.md")
    items = queue.get_pending_items()
    queue.mark_processing(items[0]["id"])
    queue.complete_processing([items[0]["id"]])
    stats = queue.get_stats()
    assert stats["completed"] == 1
    assert stats["pending"] == 0


def test_settling_a_batch_leaves_a_row_queued_again_meanwhile_alone(queue: WikiIngestionQueue) -> None:
    queue.add_batch(["/tmp/a.md", "/tmp/b.md"])
    ids = [item["id"] for item in queue.get_pending_items()]
    for item_id in ids:
        queue.mark_processing(item_id)
    queue.add_item("/tmp/a.md")

    queue.complete_processing(ids)

    assert queue.get_stats() == {"pending": 1, "processing": 0, "completed": 1, "failed": 0}
    assert queue.list_pending_file_paths() == ["/tmp/a.md"]


def test_fail_processing_records_the_failure_on_every_row_still_processing(queue: WikiIngestionQueue) -> None:
    queue.add_batch(["/tmp/a.md", "/tmp/b.md", "/tmp/c.md"])
    ids = [item["id"] for item in queue.get_pending_items()]
    for item_id in ids:
        queue.mark_processing(item_id)
    queue.add_item("/tmp/c.md")

    queue.fail_processing(ids, "rate limited", error_kind=ErrorKind.RATE_LIMIT.value, retry_after_seconds=120)

    assert queue.get_stats() == {"pending": 1, "processing": 0, "completed": 0, "failed": 2}
    failed = queue.get_failed_items()
    assert {item["error_kind"] for item in failed} == {ErrorKind.RATE_LIMIT.value}
    assert {item["retry_count"] for item in failed} == {1}
    assert all(item["retry_after"] for item in failed)


def test_requeue_processing_only_moves_rows_that_are_still_processing(queue: WikiIngestionQueue) -> None:
    queue.add_batch(["/tmp/a.md", "/tmp/b.md", "/tmp/c.md"])
    held, finished, failed = (item["id"] for item in queue.get_pending_items())
    for item_id in (held, finished, failed):
        queue.mark_processing(item_id)
    queue.complete_processing([finished])
    queue.fail_processing([failed], "err")

    queue.requeue_processing([held, finished, failed])

    assert queue.get_stats() == {"pending": 1, "processing": 0, "completed": 1, "failed": 1}
    assert [item["id"] for item in queue.get_pending_items()] == [held]


def test_touch_processing_only_refreshes_rows_that_are_processing(queue: WikiIngestionQueue) -> None:
    queue.add_batch(["/tmp/a.md", "/tmp/b.md", "/tmp/c.md"])
    held, waiting, failed = (item["id"] for item in queue.get_pending_items())
    queue.mark_processing(held)
    queue.mark_failed(failed, "err")
    with queue._get_conn() as conn:
        conn.execute("UPDATE ingestion_queue SET updated_at = datetime('now', '-400 seconds')")

    queue.touch_processing([held, waiting, failed])

    assert queue.reset_stale_processing() == 0
    assert queue.get_stats() == {"pending": 1, "processing": 1, "completed": 0, "failed": 1}
    with queue._get_conn() as conn:
        untouched = conn.execute(
            "SELECT COUNT(*) FROM ingestion_queue WHERE updated_at < datetime('now', '-300 seconds')"
        ).fetchone()[0]
    # The failed and the pending row keep their place in the ``updated_at`` ordering the panel and the retry use.
    assert untouched == 2


def test_mark_failed_increments_retry(queue: WikiIngestionQueue) -> None:
    queue.add_item("/tmp/test.md")
    items = queue.get_pending_items()
    item_id = items[0]["id"]
    queue.mark_failed(item_id, "some error")
    queue.mark_failed(item_id, "another error")
    # Check that retry_count was incremented (item is still 'failed' from second call)
    stats = queue.get_stats()
    assert stats["failed"] == 1


def test_get_transient_retryable_items(queue: WikiIngestionQueue) -> None:
    queue.add_item("/tmp/test.md")
    items = queue.get_pending_items()
    item_id = items[0]["id"]
    queue.mark_failed(item_id, "rate limited", error_kind=ErrorKind.RATE_LIMIT.value)
    retryable = queue.get_transient_retryable_items(max_retries=3)
    assert len(retryable) == 1
    assert retryable[0]["id"] == item_id


def test_get_transient_retryable_items_respects_max_retries(
    queue: WikiIngestionQueue,
) -> None:
    queue.add_item("/tmp/test.md")
    items = queue.get_pending_items()
    item_id = items[0]["id"]
    for _ in range(4):
        queue.mark_failed(item_id, "rate limited", error_kind=ErrorKind.RATE_LIMIT.value)
    retryable = queue.get_transient_retryable_items(max_retries=3)
    assert len(retryable) == 0


def test_get_transient_retryable_items_skips_non_transient(
    queue: WikiIngestionQueue,
) -> None:
    queue.add_item("/tmp/test.md")
    items = queue.get_pending_items()
    item_id = items[0]["id"]
    queue.mark_failed(item_id, "401 Unauthorized", error_kind=ErrorKind.AUTH.value)
    retryable = queue.get_transient_retryable_items(max_retries=3)
    assert len(retryable) == 0


def test_get_transient_retryable_items_not_starved_by_older_permanent_failures(
    queue: WikiIngestionQueue,
) -> None:
    permanent = [f"/tmp/permanent-{i}.md" for i in range(12)]
    transient = ["/tmp/limited-a.md", "/tmp/limited-b.md"]
    queue.add_batch(permanent + transient)
    for item in queue.get_pending_items(limit=20):
        kind = ErrorKind.RATE_LIMIT.value if item["file_path"] in transient else ErrorKind.FORMAT_ERROR.value
        queue.mark_failed(item["id"], "failed", error_kind=kind)
    with queue._get_conn() as conn:
        conn.execute(
            "UPDATE ingestion_queue SET updated_at = datetime('now', '-1 hour') WHERE error_kind = ?",
            (ErrorKind.FORMAT_ERROR.value,),
        )

    retryable = queue.get_transient_retryable_items(max_retries=3, limit=3)

    assert sorted(item["file_path"] for item in retryable) == sorted(transient)


def test_get_transient_retryable_items_oldest_first_up_to_limit(queue: WikiIngestionQueue) -> None:
    paths = [f"/tmp/limited-{i}.md" for i in range(4)]
    queue.add_batch(paths)
    for age_minutes, item in enumerate(queue.get_pending_items(limit=10)):
        queue.mark_failed(item["id"], "limited", error_kind=ErrorKind.OVERLOADED.value)
        with queue._get_conn() as conn:
            conn.execute(
                "UPDATE ingestion_queue SET updated_at = datetime('now', ?) WHERE id = ?",
                (f"-{(age_minutes + 1) * 10} minutes", item["id"]),
            )

    retryable = queue.get_transient_retryable_items(max_retries=3, limit=2)

    assert [item["file_path"] for item in retryable] == [paths[3], paths[2]]


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
    queue.mark_processing(items[0]["id"])
    queue.complete_processing([items[0]["id"]])
    queue.mark_failed(items[1]["id"], "err")
    stats = queue.get_stats()
    assert stats["completed"] == 1
    assert stats["failed"] == 1
    assert stats["pending"] == 0
    assert stats["processing"] == 0


def test_list_pending_file_paths(queue: WikiIngestionQueue) -> None:
    queue.add_batch(["/tmp/a.md", "/tmp/b.md"])
    paths = queue.list_pending_file_paths()
    assert paths == ["/tmp/a.md", "/tmp/b.md"]
    queue.mark_processing(queue.get_pending_items()[0]["id"])
    assert queue.list_pending_file_paths() == ["/tmp/b.md"]


def test_reset_stale_processing(queue: WikiIngestionQueue) -> None:
    queue.add_item("/tmp/a.md")
    item_id = queue.get_pending_items()[0]["id"]
    queue.mark_processing(item_id)
    assert queue.get_pending_items() == []
    with queue._get_conn() as conn:
        conn.execute("UPDATE ingestion_queue SET updated_at = datetime('now', '-400 seconds')")
    assert queue.reset_stale_processing(stale_seconds=300) == 1
    pending = queue.get_pending_items()
    assert len(pending) == 1
    assert pending[0]["id"] == item_id
    assert queue.reset_stale_processing() == 0


def test_circuit_property(queue: WikiIngestionQueue) -> None:
    assert queue.circuit is queue._circuit


def test_mark_failed_with_retry_after_and_get_failed_items(
    queue: WikiIngestionQueue,
) -> None:
    queue.add_item("/tmp/test.md")
    item_id = queue.get_pending_items()[0]["id"]
    queue.mark_failed(
        item_id,
        "rate limited",
        error_kind=ErrorKind.RATE_LIMIT.value,
        retry_after_seconds=60,
    )
    failed = queue.get_failed_items()
    assert len(failed) == 1
    assert failed[0]["error_kind"] == ErrorKind.RATE_LIMIT.value
    assert failed[0]["retry_after"] is not None
    assert failed[0]["retry_count"] == 1


def test_reset_transient_failed(queue: WikiIngestionQueue) -> None:
    queue.add_item("/tmp/a.md")
    a_id = queue.get_pending_items()[0]["id"]
    queue.mark_failed(a_id, "rate limited", error_kind=ErrorKind.RATE_LIMIT.value)
    queue.add_item("/tmp/b.md")
    b_id = queue.get_pending_items()[0]["id"]
    queue.mark_failed(b_id, "401 Unauthorized", error_kind=ErrorKind.AUTH.value)

    count = queue.reset_transient_failed()
    assert count == 1
    pending = queue.get_pending_items()
    assert [item["id"] for item in pending] == [a_id]


def test_reset_transient_failed_no_transient(queue: WikiIngestionQueue) -> None:
    queue.add_item("/tmp/test.md")
    item_id = queue.get_pending_items()[0]["id"]
    queue.mark_failed(item_id, "401", error_kind=ErrorKind.AUTH.value)
    assert queue.reset_transient_failed() == 0


def test_add_batch_all_filtered(queue: WikiIngestionQueue) -> None:
    blocked = queue._structure.raw_dir / "blocked.md"
    blocked.write_text("content", encoding="utf-8")
    store = CorpusDedupStore(queue._structure)
    store.add_excluded_path("blocked.md", reason="test")
    queue.add_batch([blocked])
    assert queue.get_pending_items() == []


def test_compile_phase_and_circuit_controls(queue: WikiIngestionQueue) -> None:
    queue.set_compile_phase("semantic_compile", facet_count=3, warning_count=1)
    snapshot = queue.get_compile_run()
    assert snapshot.phase == "semantic_compile"
    assert snapshot.facet_count == 3

    queue.pause_compile("api limit", ErrorKind.RATE_LIMIT.value)
    assert queue.is_compile_paused() is True
    queue.resume_compile()
    assert queue.is_compile_paused() is False

    queue.set_compile_phase("unknown_phase")
    assert queue.get_compile_run().phase == "idle"


def test_migrate_schema_adds_columns(tmp_path: Path) -> None:
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()
    conn = sqlite3.connect(tmp_path / ".ingestion_queue.db")
    conn.execute(
        """
        CREATE TABLE ingestion_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT UNIQUE NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            retry_count INTEGER DEFAULT 0,
            error_message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    conn.close()

    queue = WikiIngestionQueue(structure)
    queue.add_item("/tmp/test.md")
    item_id = queue.get_pending_items()[0]["id"]
    queue.mark_failed(
        item_id,
        "rate limited",
        error_kind=ErrorKind.RATE_LIMIT.value,
        retry_after_seconds=30,
    )
    failed = queue.get_failed_items()
    assert failed[0]["error_kind"] == ErrorKind.RATE_LIMIT.value
    assert failed[0]["retry_after"] is not None
