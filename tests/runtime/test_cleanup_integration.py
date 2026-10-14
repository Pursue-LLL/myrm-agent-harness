"""Integration tests for context file cleanup with the access tracker."""

from __future__ import annotations

import os
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.runtime.context.cleanup import CONTEXT_RETENTION_DAYS, cleanup_context_files_async
from myrm_agent_harness.runtime.context.file_access_tracker import FileAccessTracker, reset_tracker
from myrm_agent_harness.runtime.context.instance_metrics import ContextMetrics, set_context_metrics
from myrm_agent_harness.runtime.paths import execution_paths

_DAY_S = 86400


@pytest.fixture
def context_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Temporary context root, bound the way the startup shim rebinds it."""
    root = tmp_path / ".context"
    root.mkdir()
    monkeypatch.setattr(execution_paths, "CONTEXT_ROOT", str(root))
    return root


@pytest.fixture
async def access_tracker(tmp_path: Path) -> AsyncIterator[FileAccessTracker]:
    tracker = FileAccessTracker(db_path=str(tmp_path / "access.db"))
    await tracker._ensure_initialized()
    yield tracker
    await reset_tracker()


def _create_aged_file(path: Path, age_days: float) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("content")
    stamp = time.time() - age_days * _DAY_S
    os.utime(path, (stamp, stamp))
    return path


async def _record_read(tracker: FileAccessTracker, path: Path, *, days_ago: float = 0) -> None:
    """Record a read, optionally backdated (the tracker only stamps 'now')."""
    await tracker.record_access(str(path), "chat_abc")
    if days_ago:
        import aiosqlite

        stamp = (datetime.now(UTC) - timedelta(days=days_ago)).isoformat()
        async with aiosqlite.connect(tracker._db_path) as db:
            await db.execute("UPDATE file_access SET last_accessed_at = ? WHERE file_path = ?", (stamp, str(path)))
            await db.commit()


@pytest.mark.asyncio
async def test_a_recorded_read_keeps_a_file_whose_modification_time_is_old(
    context_root: Path, access_tracker: FileAccessTracker
) -> None:
    read = _create_aged_file(context_root / "chat_abc" / "compacted" / "read.txt", age_days=60)
    unread = _create_aged_file(context_root / "chat_abc" / "compacted" / "unread.txt", age_days=60)
    await _record_read(access_tracker, read)

    removed = await cleanup_context_files_async(access_tracker=access_tracker)

    assert removed == 1
    assert read.exists()
    assert not unread.exists()


@pytest.mark.asyncio
async def test_a_read_outside_the_window_no_longer_protects_a_file(
    context_root: Path, access_tracker: FileAccessTracker
) -> None:
    stale = _create_aged_file(context_root / "chat_abc" / "compacted" / "stale.txt", age_days=60)
    await _record_read(access_tracker, stale, days_ago=CONTEXT_RETENTION_DAYS + 1)

    assert await cleanup_context_files_async(access_tracker=access_tracker) == 1
    assert not stale.exists()


@pytest.mark.asyncio
async def test_the_same_window_governs_reads_and_writes(context_root: Path, access_tracker: FileAccessTracker) -> None:
    inside = _create_aged_file(
        context_root / "chat_abc" / "evicted" / "inside.txt", age_days=CONTEXT_RETENTION_DAYS - 1
    )
    outside = _create_aged_file(
        context_root / "chat_abc" / "evicted" / "outside.txt", age_days=CONTEXT_RETENTION_DAYS + 1
    )

    removed = await cleanup_context_files_async(access_tracker=access_tracker)

    assert removed == 1
    assert inside.exists()
    assert not outside.exists()


@pytest.mark.asyncio
async def test_cleanup_without_a_tracker_falls_back_to_modification_time(context_root: Path) -> None:
    stale = _create_aged_file(context_root / "chat_fail" / "compacted" / "file.txt", age_days=30)

    with patch(
        "myrm_agent_harness.runtime.context.file_access_tracker.get_file_access_tracker",
        new_callable=AsyncMock,
        side_effect=RuntimeError("DB unavailable"),
    ):
        removed = await cleanup_context_files_async()

    assert removed == 1
    assert not stale.exists()


@pytest.mark.asyncio
async def test_cleanup_uses_the_shared_tracker_when_none_is_given(context_root: Path) -> None:
    _create_aged_file(context_root / "chat_auto" / "compacted" / "file.txt", age_days=30)
    tracker = AsyncMock()
    tracker.batch_check_files.return_value = {}
    tracker.get_statistics.return_value = {"total_files": 0}

    with patch(
        "myrm_agent_harness.runtime.context.file_access_tracker.get_file_access_tracker",
        new_callable=AsyncMock,
        return_value=tracker,
    ):
        removed = await cleanup_context_files_async()

    assert removed == 1
    tracker.batch_check_files.assert_awaited_once()


@pytest.mark.asyncio
async def test_cleanup_async_no_context_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(execution_paths, "CONTEXT_ROOT", "/nonexistent")

    assert await cleanup_context_files_async(access_tracker=AsyncMock()) == 0


@pytest.mark.asyncio
async def test_empty_directories_are_removed(context_root: Path, access_tracker: FileAccessTracker) -> None:
    session_dir = context_root / "chat_abc" / "compacted"
    _create_aged_file(session_dir / "file1.txt", age_days=30)

    await cleanup_context_files_async(access_tracker=access_tracker)

    assert not session_dir.exists()
    assert not session_dir.parent.exists()


@pytest.mark.asyncio
async def test_orphan_tracking_records_are_removed(context_root: Path, access_tracker: FileAccessTracker) -> None:
    file1 = _create_aged_file(context_root / "chat_abc" / "compacted" / "file1.txt", age_days=30)
    await _record_read(access_tracker, file1, days_ago=CONTEXT_RETENTION_DAYS + 1)

    await cleanup_context_files_async(access_tracker=access_tracker)

    assert await access_tracker.get_last_access(str(file1)) is None


@pytest.mark.asyncio
async def test_sessions_are_processed_in_batches(context_root: Path, access_tracker: FileAccessTracker) -> None:
    for i in range(250):
        _create_aged_file(context_root / f"chat_{i}" / "compacted" / "file.txt", age_days=30)

    removed = await cleanup_context_files_async(batch_size=50, access_tracker=access_tracker)

    assert removed == 250


@pytest.mark.asyncio
async def test_cleanup_respects_the_timeout(context_root: Path, access_tracker: FileAccessTracker) -> None:
    files = [_create_aged_file(context_root / f"chat_{i}" / "compacted" / "file.txt", age_days=30) for i in range(10)]

    removed = await cleanup_context_files_async(timeout_seconds=0, batch_size=1, access_tracker=access_tracker)

    assert removed == 0
    assert all(f.exists() for f in files)


@pytest.mark.asyncio
async def test_nested_directories_are_left_alone(context_root: Path, access_tracker: FileAccessTracker) -> None:
    nested = context_root / "chat_nested" / "compacted" / "subdir"
    nested.mkdir(parents=True)

    removed = await cleanup_context_files_async(retention_days=0, access_tracker=access_tracker)

    assert removed == 0


@pytest.mark.asyncio
async def test_cleanup_reports_into_bound_context_metrics(
    context_root: Path, access_tracker: FileAccessTracker
) -> None:
    """Phase timings, protection-rule hits and batch queries land in the ContextMetrics bound to the task."""
    tracked = _create_aged_file(context_root / "chat_abc" / "compacted" / "tracked.txt", age_days=60)
    _create_aged_file(context_root / "chat_abc" / "compacted" / "stale.txt", age_days=60)
    _create_aged_file(context_root / "chat_abc" / "compacted" / "fresh.txt", age_days=1)
    await _record_read(access_tracker, tracked)

    metrics = ContextMetrics()
    set_context_metrics(metrics)
    try:
        removed = await cleanup_context_files_async(access_tracker=access_tracker)
    finally:
        set_context_metrics(None)

    assert removed == 1
    assert metrics.protection_rule_hits["access_tracked"] == 1
    assert metrics.protection_rule_hits["mtime_fallback"] == 1
    assert {"file_scanning", "deletion"} <= set(metrics.cleanup_phase_durations_ms)
    assert metrics.batch_query_count["access_check"] == 1
