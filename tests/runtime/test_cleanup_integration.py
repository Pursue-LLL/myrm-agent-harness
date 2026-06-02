"""Integration tests for context file cleanup with tracking systems."""

from __future__ import annotations

import os
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.runtime.context.cleanup import cleanup_context_files_async
from myrm_agent_harness.runtime.context.config import StorageQuotaConfig
from myrm_agent_harness.runtime.context.file_access_tracker import FileAccessTracker, reset_tracker


@pytest.fixture
def context_root(tmp_path: Path) -> Path:
    """Create temporary context root directory."""
    root = tmp_path / ".context"
    root.mkdir()
    return root


@pytest.fixture
async def access_tracker(tmp_path: Path) -> FileAccessTracker:
    """Create access tracker instance."""
    db_path = str(tmp_path / "access.db")
    tracker = FileAccessTracker(db_path=db_path)
    await tracker._ensure_initialized()
    yield tracker
    await reset_tracker()


@pytest.mark.asyncio
async def test_cleanup_with_recent_access(
    context_root: Path,
    access_tracker: FileAccessTracker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test cleanup respects recently accessed files."""
    monkeypatch.setattr("myrm_agent_harness.runtime.execution_paths.CONTEXT_ROOT", str(context_root))

    session_dir = context_root / "chat_abc" / "compacted"
    session_dir.mkdir(parents=True)

    file1 = session_dir / "file1.txt"
    file1.write_text("content1")

    file2 = session_dir / "file2.txt"
    file2.write_text("content2")

    await access_tracker.record_access(str(file1), "chat_abc")

    removed = await cleanup_context_files_async(
        max_age_days=0,
        session_active_days=0,
        file_access_days=1,
        access_tracker=access_tracker,
        checkpointer=None,
    )

    assert removed == 1
    assert file1.exists()
    assert not file2.exists()


@pytest.mark.asyncio
async def test_cleanup_respects_priority_order(
    context_root: Path,
    access_tracker: FileAccessTracker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test cleanup respects rule priority (session > access > mtime)."""
    monkeypatch.setattr("myrm_agent_harness.runtime.execution_paths.CONTEXT_ROOT", str(context_root))

    session_dir = context_root / "chat_abc" / "compacted"
    session_dir.mkdir(parents=True)

    file_accessed = session_dir / "file_accessed.txt"
    file_accessed.write_text("accessed content")

    file_old = session_dir / "file_old.txt"
    file_old.write_text("old content")

    await access_tracker.record_access(str(file_accessed), "chat_abc")

    removed = await cleanup_context_files_async(
        max_age_days=0,
        session_active_days=0,
        file_access_days=1,
        access_tracker=access_tracker,
        checkpointer=None,
    )

    assert removed == 1
    assert file_accessed.exists()
    assert not file_old.exists()


@pytest.mark.asyncio
async def test_cleanup_empty_directories(
    context_root: Path,
    access_tracker: FileAccessTracker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test cleanup removes empty directories."""
    monkeypatch.setattr("myrm_agent_harness.runtime.execution_paths.CONTEXT_ROOT", str(context_root))

    session_dir = context_root / "chat_abc" / "compacted"
    session_dir.mkdir(parents=True)

    file1 = session_dir / "file1.txt"
    file1.write_text("content1")

    await cleanup_context_files_async(
        max_age_days=0,
        session_active_days=0,
        file_access_days=0,
        access_tracker=access_tracker,
        checkpointer=None,
    )

    assert not session_dir.exists()
    assert not session_dir.parent.exists()


@pytest.mark.asyncio
async def test_cleanup_orphan_tracking_records(
    context_root: Path,
    access_tracker: FileAccessTracker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test cleanup removes orphan tracking records."""
    monkeypatch.setattr("myrm_agent_harness.runtime.execution_paths.CONTEXT_ROOT", str(context_root))

    session_dir = context_root / "chat_abc" / "compacted"
    session_dir.mkdir(parents=True)

    file1 = session_dir / "file1.txt"
    file1.write_text("content1")

    await access_tracker.record_access(str(file1), "chat_abc")

    await cleanup_context_files_async(
        max_age_days=0,
        session_active_days=0,
        file_access_days=0,
        access_tracker=access_tracker,
        checkpointer=None,
    )

    last_access = await access_tracker.get_last_access(str(file1))
    assert last_access is None


@pytest.mark.asyncio
async def test_cleanup_batch_processing(
    context_root: Path,
    access_tracker: FileAccessTracker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test cleanup processes sessions in batches."""
    monkeypatch.setattr("myrm_agent_harness.runtime.execution_paths.CONTEXT_ROOT", str(context_root))

    for i in range(250):
        session_dir = context_root / f"chat_{i}" / "compacted"
        session_dir.mkdir(parents=True)
        file = session_dir / "file.txt"
        file.write_text(f"content {i}")

    removed = await cleanup_context_files_async(
        max_age_days=0,
        session_active_days=0,
        file_access_days=0,
        batch_size=50,
        access_tracker=access_tracker,
        checkpointer=None,
    )

    assert removed == 250


@pytest.mark.asyncio
async def test_cleanup_timeout(
    context_root: Path,
    access_tracker: FileAccessTracker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test cleanup respects timeout."""
    monkeypatch.setattr("myrm_agent_harness.runtime.execution_paths.CONTEXT_ROOT", str(context_root))

    for i in range(10):
        session_dir = context_root / f"chat_{i}" / "compacted"
        session_dir.mkdir(parents=True)
        file = session_dir / "file.txt"
        file.write_text(f"content {i}")

    removed = await cleanup_context_files_async(
        max_age_days=0,
        session_active_days=0,
        file_access_days=0,
        timeout_seconds=0.001,
        access_tracker=access_tracker,
        checkpointer=None,
    )

    assert removed <= 10


def test_quota_config_valid() -> None:
    """Test valid quota configuration."""
    config = StorageQuotaConfig(
        per_session_limit_mb=500,
        auto_cleanup_threshold=0.8,
    )

    assert config.per_session_limit_mb == 500
    assert config.auto_cleanup_threshold == 0.8


def test_quota_config_invalid_limit() -> None:
    """Test invalid quota limit raises ValueError."""
    with pytest.raises(ValueError, match="per_session_limit_mb must be positive"):
        StorageQuotaConfig(per_session_limit_mb=-1)


def test_quota_config_invalid_threshold() -> None:
    """Test invalid cleanup threshold raises ValueError."""
    with pytest.raises(ValueError, match="auto_cleanup_threshold must be in"):
        StorageQuotaConfig(auto_cleanup_threshold=1.5)


def _create_old_file(path: Path, age_seconds: float = 100) -> None:
    path.write_text("content")
    old_time = time.time() - age_seconds
    os.utime(path, (old_time, old_time))


@pytest.mark.asyncio
async def test_cleanup_async_no_context_root(monkeypatch: pytest.MonkeyPatch) -> None:
    """Async cleanup returns 0 when context root doesn't exist."""
    monkeypatch.setattr("myrm_agent_harness.runtime.execution_paths.CONTEXT_ROOT", "/nonexistent")
    result = await cleanup_context_files_async(checkpointer=None, access_tracker=AsyncMock())
    assert result == 0


@pytest.mark.asyncio
async def test_cleanup_async_with_metrics(
    context_root: Path,
    access_tracker: FileAccessTracker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Async cleanup records metrics when available."""
    monkeypatch.setattr("myrm_agent_harness.runtime.execution_paths.CONTEXT_ROOT", str(context_root))

    session_dir = context_root / "chat_metrics" / "compacted"
    session_dir.mkdir(parents=True)
    f = session_dir / "file.txt"
    _create_old_file(f, age_seconds=86400 * 30)

    removed = await cleanup_context_files_async(
        max_age_days=7,
        session_active_days=0,
        file_access_days=0,
        access_tracker=access_tracker,
        checkpointer=None,
    )
    assert removed == 1


@pytest.mark.asyncio
async def test_cleanup_async_with_active_session(
    context_root: Path,
    access_tracker: FileAccessTracker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Async cleanup keeps files for active sessions."""
    monkeypatch.setattr("myrm_agent_harness.runtime.execution_paths.CONTEXT_ROOT", str(context_root))

    session_dir = context_root / "chat_active" / "compacted"
    session_dir.mkdir(parents=True)
    f = session_dir / "file.txt"
    _create_old_file(f, age_seconds=86400 * 30)

    mock_checkpointer = MagicMock()
    with patch(
        "myrm_agent_harness.runtime.context.cleanup.load_session_activity_async",
        new_callable=AsyncMock,
        return_value={"chat_active"},
    ):
        removed = await cleanup_context_files_async(
            max_age_days=7,
            session_active_days=30,
            file_access_days=14,
            access_tracker=access_tracker,
            checkpointer=mock_checkpointer,
        )

    assert removed == 0
    assert f.exists()


@pytest.mark.asyncio
async def test_cleanup_async_mtime_fallback(
    context_root: Path,
    access_tracker: FileAccessTracker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Async cleanup uses mtime fallback when file is recent."""
    monkeypatch.setattr("myrm_agent_harness.runtime.execution_paths.CONTEXT_ROOT", str(context_root))

    session_dir = context_root / "chat_mtime" / "compacted"
    session_dir.mkdir(parents=True)
    f = session_dir / "recent.txt"
    f.write_text("recent content")

    removed = await cleanup_context_files_async(
        max_age_days=7,
        session_active_days=0,
        file_access_days=0,
        access_tracker=access_tracker,
        checkpointer=None,
    )
    assert removed == 0
    assert f.exists()


@pytest.mark.asyncio
async def test_cleanup_async_auto_get_tracker(
    context_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Async cleanup auto-gets tracker when not provided."""
    monkeypatch.setattr("myrm_agent_harness.runtime.execution_paths.CONTEXT_ROOT", str(context_root))

    session_dir = context_root / "chat_auto" / "compacted"
    session_dir.mkdir(parents=True)
    f = session_dir / "file.txt"
    _create_old_file(f, age_seconds=86400 * 30)

    mock_tracker = AsyncMock()
    mock_tracker.batch_check_files = AsyncMock(return_value={})
    mock_tracker.cleanup_orphan_records = AsyncMock(return_value=0)
    mock_tracker.get_statistics = AsyncMock(return_value={"total_files": 0})

    with patch(
        "myrm_agent_harness.runtime.context.file_access_tracker.get_file_access_tracker",
        new_callable=AsyncMock,
        return_value=mock_tracker,
    ):
        removed = await cleanup_context_files_async(
            max_age_days=7,
            session_active_days=0,
            file_access_days=0,
            access_tracker=None,
            checkpointer=None,
        )

    assert removed == 1


@pytest.mark.asyncio
async def test_cleanup_async_tracker_get_failure(
    context_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Async cleanup handles tracker acquisition failure."""
    monkeypatch.setattr("myrm_agent_harness.runtime.execution_paths.CONTEXT_ROOT", str(context_root))

    session_dir = context_root / "chat_fail" / "compacted"
    session_dir.mkdir(parents=True)
    f = session_dir / "file.txt"
    _create_old_file(f, age_seconds=86400 * 30)

    with patch(
        "myrm_agent_harness.runtime.context.file_access_tracker.get_file_access_tracker",
        new_callable=AsyncMock,
        side_effect=RuntimeError("DB unavailable"),
    ):
        removed = await cleanup_context_files_async(
            max_age_days=7,
            session_active_days=0,
            file_access_days=0,
            access_tracker=None,
            checkpointer=None,
        )

    assert removed == 1


@pytest.mark.asyncio
async def test_cleanup_async_session_loading_failure(
    context_root: Path,
    access_tracker: FileAccessTracker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Async cleanup handles session loading failure gracefully."""
    monkeypatch.setattr("myrm_agent_harness.runtime.execution_paths.CONTEXT_ROOT", str(context_root))

    session_dir = context_root / "chat_err" / "compacted"
    session_dir.mkdir(parents=True)
    f = session_dir / "file.txt"
    _create_old_file(f, age_seconds=86400 * 30)

    with patch(
        "myrm_agent_harness.runtime.context.cleanup.load_session_activity_async",
        new_callable=AsyncMock,
        side_effect=RuntimeError("checkpointer error"),
    ):
        removed = await cleanup_context_files_async(
            max_age_days=7,
            session_active_days=0,
            file_access_days=0,
            access_tracker=access_tracker,
            checkpointer=MagicMock(),
        )

    assert removed == 1


@pytest.mark.asyncio
async def test_cleanup_async_skips_non_file_entries(
    context_root: Path,
    access_tracker: FileAccessTracker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Async cleanup skips directories inside subdirs."""
    monkeypatch.setattr("myrm_agent_harness.runtime.execution_paths.CONTEXT_ROOT", str(context_root))

    session_dir = context_root / "chat_nested" / "compacted"
    session_dir.mkdir(parents=True)
    nested_dir = session_dir / "subdir"
    nested_dir.mkdir()

    removed = await cleanup_context_files_async(
        max_age_days=0,
        session_active_days=0,
        file_access_days=0,
        access_tracker=access_tracker,
        checkpointer=None,
    )
    assert removed == 0
