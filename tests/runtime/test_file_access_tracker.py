"""Tests for file access tracking system."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest

from myrm_agent_harness.runtime.context.file_access_tracker import FileAccessTracker, reset_tracker


@pytest.fixture
async def temp_db(tmp_path: Path) -> str:
    """Create temporary database for testing."""
    db_path = str(tmp_path / "test_access.db")
    yield db_path
    await reset_tracker()


@pytest.fixture
async def tracker(temp_db: str) -> FileAccessTracker:
    """Create tracker instance for testing."""
    tracker = FileAccessTracker(db_path=temp_db)
    await tracker._ensure_initialized()
    return tracker


@pytest.mark.asyncio
async def test_record_and_get_access(tracker: FileAccessTracker) -> None:
    """Test recording and retrieving file access."""
    file_path = "/persistent/.context/chat_abc/compacted/file1.txt"
    session_id = "chat_abc"

    await tracker.record_access(file_path, session_id)
    last_access = await tracker.get_last_access(file_path)

    assert last_access is not None
    assert (datetime.now(UTC) - last_access).total_seconds() < 5


@pytest.mark.asyncio
async def test_multiple_accesses_increment_count(tracker: FileAccessTracker) -> None:
    """Test that multiple accesses increment access count."""
    file_path = "/persistent/.context/chat_abc/compacted/file1.txt"
    session_id = "chat_abc"

    await tracker.record_access(file_path, session_id)
    await tracker.record_access(file_path, session_id)
    await tracker.record_access(file_path, session_id)

    files = await tracker.get_session_files(session_id)
    assert len(files) == 1
    assert files[0][0] == file_path
    assert files[0][2] == 3


@pytest.mark.asyncio
async def test_get_session_files_with_filter(tracker: FileAccessTracker) -> None:
    """Test filtering session files by access time."""
    session_id = "chat_abc"

    await tracker.record_access("/persistent/.context/chat_abc/compacted/file1.txt", session_id)
    await asyncio.sleep(0.2)
    threshold = datetime.now(UTC)
    await asyncio.sleep(0.1)
    await tracker.record_access("/persistent/.context/chat_abc/compacted/file2.txt", session_id)

    recent_files = await tracker.get_session_files(session_id, accessed_after=threshold)

    assert len(recent_files) == 1
    assert "file2.txt" in recent_files[0][0]


@pytest.mark.asyncio
async def test_cleanup_orphan_records(tracker: FileAccessTracker) -> None:
    """Test cleanup of orphan access records."""
    await tracker.record_access("/persistent/.context/chat_abc/compacted/file1.txt", "chat_abc")
    await tracker.record_access("/persistent/.context/chat_abc/compacted/file2.txt", "chat_abc")
    await tracker.record_access("/persistent/.context/chat_abc/compacted/file3.txt", "chat_abc")

    existing_files = {"/persistent/.context/chat_abc/compacted/file1.txt"}
    removed = await tracker.cleanup_orphan_records(existing_files)

    assert removed == 2
    stats = await tracker.get_statistics()
    assert stats["total_files"] == 1


@pytest.mark.asyncio
async def test_extract_session_id(tracker: FileAccessTracker) -> None:
    """Test session ID extraction from file path."""
    file_path = "/persistent/.context/chat_xyz/compacted/file1.txt"
    session_id = tracker._extract_session_id(file_path)

    assert session_id == "chat_xyz"


@pytest.mark.asyncio
async def test_delete_session_records(tracker: FileAccessTracker) -> None:
    """Test deleting all records for a session."""
    await tracker.record_access("/persistent/.context/chat_abc/compacted/file1.txt", "chat_abc")
    await tracker.record_access("/persistent/.context/chat_abc/compacted/file2.txt", "chat_abc")
    await tracker.record_access("/persistent/.context/chat_xyz/compacted/file3.txt", "chat_xyz")

    removed = await tracker.delete_session_records("chat_abc")

    assert removed == 2
    stats = await tracker.get_statistics()
    assert stats["total_files"] == 1


@pytest.mark.asyncio
async def test_statistics(tracker: FileAccessTracker) -> None:
    """Test statistics collection."""
    await tracker.record_access("/persistent/.context/chat_abc/compacted/file1.txt", "chat_abc")
    await tracker.record_access("/persistent/.context/chat_xyz/compacted/file2.txt", "chat_xyz")
    await tracker.record_access("/persistent/.context/chat_abc/compacted/file3.txt", "chat_abc")

    stats = await tracker.get_statistics()

    assert stats["total_files"] == 3
    assert stats["total_sessions"] == 2
    assert stats["total_accesses"] == 3


@pytest.mark.asyncio
async def test_concurrent_access(tracker: FileAccessTracker) -> None:
    """Test thread-safe concurrent access."""
    file_path = "/persistent/.context/chat_abc/compacted/file1.txt"
    session_id = "chat_abc"

    await asyncio.gather(*[tracker.record_access(file_path, session_id) for _ in range(10)])

    files = await tracker.get_session_files(session_id)
    assert len(files) == 1
    assert files[0][2] == 10


@pytest.mark.asyncio
async def test_get_nonexistent_file(tracker: FileAccessTracker) -> None:
    """Test getting access time for non-existent file."""
    last_access = await tracker.get_last_access("/nonexistent/file.txt")

    assert last_access is None


@pytest.mark.asyncio
async def test_record_access_auto_extract_session_id(tracker: FileAccessTracker) -> None:
    """Test record_access auto-extracts session_id from path."""
    file_path = "/persistent/.context/chat_auto/compacted/file.txt"
    await tracker.record_access(file_path)

    files = await tracker.get_session_files("chat_auto")
    assert len(files) == 1
    assert files[0][0] == file_path


@pytest.mark.asyncio
async def test_extract_session_id_unknown(tracker: FileAccessTracker) -> None:
    """Test session_id extraction returns 'unknown' for invalid paths."""
    assert tracker._extract_session_id("/tmp/random/file.txt") == "unknown"
    assert tracker._extract_session_id("no_slashes") == "unknown"


@pytest.mark.asyncio
async def test_batch_check_files_empty(tracker: FileAccessTracker) -> None:
    """Test batch_check_files with empty list."""
    result = await tracker.batch_check_files([], datetime.now(UTC))
    assert result == {}


@pytest.mark.asyncio
async def test_batch_check_files_returns_tracked(tracker: FileAccessTracker) -> None:
    """Test batch_check_files returns only tracked files."""
    f1 = "/persistent/.context/chat_a/compacted/f1.txt"
    f2 = "/persistent/.context/chat_a/compacted/f2.txt"
    f3 = "/persistent/.context/chat_a/compacted/f3.txt"

    await tracker.record_access(f1, "chat_a")
    await tracker.record_access(f2, "chat_a")

    result = await tracker.batch_check_files([f1, f2, f3], datetime.now(UTC))
    assert f1 in result
    assert f2 in result
    assert f3 not in result


@pytest.mark.asyncio
async def test_cleanup_orphan_records_none_to_clean(tracker: FileAccessTracker) -> None:
    """Test cleanup_orphan_records when all files exist."""
    f1 = "/persistent/.context/chat_a/compacted/f1.txt"
    await tracker.record_access(f1, "chat_a")

    removed = await tracker.cleanup_orphan_records({f1})
    assert removed == 0


@pytest.mark.asyncio
async def test_get_session_files_no_filter(tracker: FileAccessTracker) -> None:
    """Test get_session_files without access_after filter."""
    f1 = "/persistent/.context/chat_x/compacted/f1.txt"
    f2 = "/persistent/.context/chat_x/compacted/f2.txt"
    await tracker.record_access(f1, "chat_x")
    await tracker.record_access(f2, "chat_x")

    files = await tracker.get_session_files("chat_x")
    assert len(files) == 2


@pytest.mark.asyncio
async def test_lazy_initialization(temp_db: str) -> None:
    """Test that tracker initializes lazily on first operation."""
    tracker = FileAccessTracker(db_path=temp_db)
    assert not tracker._initialized

    await tracker.record_access("/persistent/.context/chat_a/compacted/f.txt", "chat_a")
    assert tracker._initialized
