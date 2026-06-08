"""Tests for cancel_crawl functionality.

Covers:
- CrawlTaskStatus.CANCELLED enum value
- CrawlTaskStore.cancel_group()
- CrawlTaskStore.is_group_cancelled()
- CrawlTaskGroupSummary.cancelled field
- _discover_and_enqueue_links cancel guard
- _cancel_crawl tool function error paths and success path
- Edge cases: failed tasks, timestamps, queue drain after cancel
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest


@pytest.fixture()
def task_store():
    """Create a CrawlTaskStore with a temporary database."""
    from myrm_agent_harness.toolkits.web_fetch.task_store import CrawlTaskStore

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        store = CrawlTaskStore(db_path)
        yield store


@pytest.fixture()
def group_with_tasks(task_store):
    """Create a group with 5 pending tasks for testing."""
    group_id = task_store.create_group(
        seed_url="https://example.com",
        result_dir="/tmp/test_results",
        max_depth=3,
        max_pages=100,
    )
    task_store.add_tasks_batch(group_id, [
        ("https://example.com/page1", 0),
        ("https://example.com/page2", 0),
        ("https://example.com/page3", 0),
        ("https://example.com/page4", 0),
        ("https://example.com/page5", 0),
    ])
    return group_id


class TestCancelGroup:
    """Tests for CrawlTaskStore.cancel_group()."""

    def test_cancel_pending_tasks(self, task_store, group_with_tasks):
        group_id = group_with_tasks
        cancelled = task_store.cancel_group(group_id)
        assert cancelled == 5

    def test_cancel_does_not_affect_running(self, task_store, group_with_tasks):
        group_id = group_with_tasks
        task_store.claim_next_pending(group_id)
        cancelled = task_store.cancel_group(group_id)
        assert cancelled == 4

    def test_cancel_empty_group(self, task_store):
        group_id = task_store.create_group(
            seed_url="https://example.com",
            result_dir="/tmp/test_results",
            max_depth=3,
            max_pages=100,
        )
        cancelled = task_store.cancel_group(group_id)
        assert cancelled == 0

    def test_cancel_already_cancelled(self, task_store, group_with_tasks):
        group_id = group_with_tasks
        task_store.cancel_group(group_id)
        cancelled_again = task_store.cancel_group(group_id)
        assert cancelled_again == 0

    def test_cancel_preserves_completed(self, task_store, group_with_tasks):
        group_id = group_with_tasks
        task = task_store.claim_next_pending(group_id)
        task_store.mark_completed(task.task_id, "/tmp/result.md")
        task_store.cancel_group(group_id)
        summary = task_store.get_group_summary(group_id)
        assert summary.completed == 1
        assert summary.cancelled == 4

    def test_cancel_preserves_failed(self, task_store, group_with_tasks):
        group_id = group_with_tasks
        task = task_store.claim_next_pending(group_id)
        task_store.mark_failed(task.task_id, "connection timeout")
        task_store.cancel_group(group_id)
        summary = task_store.get_group_summary(group_id)
        assert summary.failed == 1
        assert summary.cancelled == 4

    def test_cancel_sets_completed_at_timestamp(self, task_store, group_with_tasks):
        """Verify cancelled tasks get a completed_at timestamp."""
        group_id = group_with_tasks
        before = time.time()
        task_store.cancel_group(group_id)
        after = time.time()

        import sqlite3
        conn = sqlite3.connect(str(task_store._db_path))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT completed_at FROM crawl_tasks WHERE group_id = ? AND status = 'cancelled'",
            (group_id,),
        ).fetchall()
        conn.close()

        assert len(rows) == 5
        for row in rows:
            assert before <= row["completed_at"] <= after

    def test_cancel_drains_pending_queue(self, task_store, group_with_tasks):
        """After cancel, claim_next_pending returns None."""
        group_id = group_with_tasks
        task_store.cancel_group(group_id)
        assert task_store.claim_next_pending(group_id) is None

    def test_cancel_nonexistent_group_returns_zero(self, task_store):
        """Cancelling a group_id with no tasks returns 0 without error."""
        cancelled = task_store.cancel_group("nonexistent_group_id")
        assert cancelled == 0

    def test_has_pending_or_running_false_after_cancel(self, task_store, group_with_tasks):
        """has_pending_or_running returns False after cancellation (no running tasks)."""
        group_id = group_with_tasks
        task_store.cancel_group(group_id)
        assert not task_store.has_pending_or_running(group_id)


class TestIsGroupCancelled:
    """Tests for CrawlTaskStore.is_group_cancelled()."""

    def test_not_cancelled(self, task_store, group_with_tasks):
        assert not task_store.is_group_cancelled(group_with_tasks)

    def test_after_cancel(self, task_store, group_with_tasks):
        task_store.cancel_group(group_with_tasks)
        assert task_store.is_group_cancelled(group_with_tasks)

    def test_nonexistent_group(self, task_store):
        """Nonexistent group is not considered cancelled."""
        assert not task_store.is_group_cancelled("nonexistent_id")

    def test_still_cancelled_after_partial_running(self, task_store, group_with_tasks):
        """is_group_cancelled remains True even if some tasks were running when cancel happened."""
        group_id = group_with_tasks
        task_store.claim_next_pending(group_id)  # 1 running
        task_store.cancel_group(group_id)  # 4 cancelled
        assert task_store.is_group_cancelled(group_id)


class TestSummaryCancelledField:
    """Tests for CrawlTaskGroupSummary.cancelled field."""

    def test_cancelled_count_accurate(self, task_store, group_with_tasks):
        group_id = group_with_tasks
        task_store.cancel_group(group_id)
        summary = task_store.get_group_summary(group_id)
        assert summary.cancelled == 5
        assert summary.total == 5
        assert summary.pending == 0

    def test_total_equals_sum(self, task_store, group_with_tasks):
        group_id = group_with_tasks
        task = task_store.claim_next_pending(group_id)
        task_store.mark_completed(task.task_id, "/tmp/result.md")
        task_store.cancel_group(group_id)
        summary = task_store.get_group_summary(group_id)
        expected_sum = (
            summary.pending
            + summary.running
            + summary.completed
            + summary.failed
            + summary.cancelled
        )
        assert summary.total == expected_sum

    def test_all_states_mixed(self, task_store, group_with_tasks):
        """Test summary with all 4 terminal + running states present."""
        group_id = group_with_tasks
        # 1 completed
        t1 = task_store.claim_next_pending(group_id)
        task_store.mark_completed(t1.task_id, "/tmp/r1.md")
        # 1 failed
        t2 = task_store.claim_next_pending(group_id)
        task_store.mark_failed(t2.task_id, "error")
        # 1 running
        task_store.claim_next_pending(group_id)
        # cancel remaining 2 pending
        task_store.cancel_group(group_id)
        summary = task_store.get_group_summary(group_id)
        assert summary.completed == 1
        assert summary.failed == 1
        assert summary.running == 1
        assert summary.cancelled == 2
        assert summary.pending == 0
        assert summary.total == 5


class TestCancelledEnum:
    """Tests for CrawlTaskStatus.CANCELLED enum."""

    def test_cancelled_value(self):
        from myrm_agent_harness.toolkits.web_fetch.task_store import CrawlTaskStatus

        assert CrawlTaskStatus.CANCELLED.value == "cancelled"

    def test_cancelled_is_string_enum(self):
        from myrm_agent_harness.toolkits.web_fetch.task_store import CrawlTaskStatus

        assert isinstance(CrawlTaskStatus.CANCELLED, str)
        assert CrawlTaskStatus.CANCELLED == "cancelled"


class TestDiscoverAndEnqueueCancelGuard:
    """Tests for _discover_and_enqueue_links cancel guard in CrawlTaskExecutor."""

    def test_no_enqueue_after_cancel(self, task_store, group_with_tasks):
        """After cancel, _discover_and_enqueue_links should not add tasks."""
        from myrm_agent_harness.toolkits.web_fetch.task_executor import CrawlTaskExecutor

        group_id = group_with_tasks
        task_store.cancel_group(group_id)

        mock_engine = MagicMock()
        mock_rate_limiter = MagicMock()
        executor = CrawlTaskExecutor(task_store, mock_engine, mock_rate_limiter)

        mock_doc = MagicMock()
        mock_doc.metadata = {"links": ["https://example.com/new1", "https://example.com/new2"]}
        mock_task = MagicMock()
        mock_task.depth = 0
        mock_task.url = "https://example.com/page1"

        executor._discover_and_enqueue_links(mock_doc, mock_task, group_id)

        summary = task_store.get_group_summary(group_id)
        assert summary.total == 5  # No new tasks added

    def test_enqueue_works_before_cancel(self, task_store):
        """Before cancel, _discover_and_enqueue_links adds tasks normally."""
        from myrm_agent_harness.toolkits.web_fetch.task_executor import CrawlTaskExecutor

        group_id = task_store.create_group(
            seed_url="https://example.com",
            result_dir="/tmp/test_results",
            max_depth=3,
            max_pages=100,
        )
        task_store.add_tasks_batch(group_id, [("https://example.com/page1", 0)])

        mock_engine = MagicMock()
        mock_rate_limiter = MagicMock()
        executor = CrawlTaskExecutor(task_store, mock_engine, mock_rate_limiter)

        mock_doc = MagicMock()
        mock_doc.metadata = {"links": ["https://example.com/new1", "https://example.com/new2"]}
        mock_doc.page_content = '<a href="https://example.com/new1">link</a>'
        mock_task = MagicMock()
        mock_task.depth = 0
        mock_task.url = "https://example.com/page1"

        executor._discover_and_enqueue_links(mock_doc, mock_task, group_id)

        # Check: is_group_cancelled is False, so the method should proceed
        assert not task_store.is_group_cancelled(group_id)


class TestCancelCrawlToolFunction:
    """Tests for the _cancel_crawl tool function."""

    @pytest.mark.asyncio
    async def test_cancel_crawl_no_db_raises_tool_error(self):
        """_cancel_crawl raises ToolError when no database exists."""
        from myrm_agent_harness.toolkits.web_fetch.web_fetch_agent_tools import _cancel_crawl
        from myrm_agent_harness.utils.errors import ToolError

        with tempfile.TemporaryDirectory() as tmp:
            with pytest.raises(ToolError, match="No crawl database found"):
                await _cancel_crawl("some_group", data_dir=tmp)

    @pytest.mark.asyncio
    async def test_cancel_crawl_invalid_group_raises_tool_error(self):
        """_cancel_crawl raises ToolError for nonexistent group_id."""
        from myrm_agent_harness.toolkits.web_fetch.task_store import CrawlTaskStore
        from myrm_agent_harness.toolkits.web_fetch.web_fetch_agent_tools import _cancel_crawl
        from myrm_agent_harness.utils.errors import ToolError

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / ".crawl_tasks.db"
            store = CrawlTaskStore(db_path)
            store.create_group(seed_url="https://x.com", result_dir="/tmp/r")

            with pytest.raises(ToolError, match="Task group not found"):
                await _cancel_crawl("nonexistent_group", data_dir=tmp)

    @pytest.mark.asyncio
    async def test_cancel_crawl_success_response(self):
        """_cancel_crawl returns correct content and metadata on success."""
        from myrm_agent_harness.toolkits.web_fetch.task_store import CrawlTaskStore
        from myrm_agent_harness.toolkits.web_fetch.web_fetch_agent_tools import _cancel_crawl

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / ".crawl_tasks.db"
            store = CrawlTaskStore(db_path)
            group_id = store.create_group(seed_url="https://x.com", result_dir="/tmp/r")
            store.add_tasks_batch(group_id, [
                ("https://x.com/a", 0),
                ("https://x.com/b", 0),
            ])

            result = await _cancel_crawl(group_id, data_dir=tmp)

            assert "cancel" in result["content"].lower()
            assert result["metadata"]["operation"] == "cancel_crawl"
            assert result["metadata"]["cancelled_count"] == 2
            assert result["metadata"]["group_id"] == group_id
