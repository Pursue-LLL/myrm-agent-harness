"""Unit tests for ContextCleanupScheduler.

Tests coverage:
1. _run_cleanup core logic (multi-level directory traversal, age-based filtering)
2. ContextCleanupScheduler lifecycle (start/stop)
3. Error handling (file permission, missing dirs)
4. Logging (CONTEXT_CLEANUP_ORPHAN)
"""

import asyncio
import logging
import os
import time
from pathlib import Path

import pytest

from myrm_agent_harness.runtime.context.cleanup_task import ContextCleanupScheduler


@pytest.mark.asyncio
async def test_cleanup_deletes_old_files(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Old context directories beyond max_age_days are deleted."""
    sandboxes_root = tmp_path / "sandboxes"
    sandboxes_root.mkdir()

    user_dir = sandboxes_root / "user_test"
    user_dir.mkdir()

    session_dir = user_dir / "chat_old"
    session_dir.mkdir()

    context_dir = session_dir / ".context" / "chat_old"
    context_dir.mkdir(parents=True)
    (context_dir / "file1.txt").write_text("old content")

    old_mtime = time.time() - (8 * 86400)
    os.utime(context_dir, (old_mtime, old_mtime))

    scheduler = ContextCleanupScheduler(sandboxes_root, max_age_days=7)

    caplog.clear()
    with caplog.at_level(logging.INFO):
        await scheduler._run_cleanup()

    assert not context_dir.exists()

    orphan_logs = [r for r in caplog.records if "CONTEXT_CLEANUP_ORPHAN" in r.message]
    assert len(orphan_logs) == 1


@pytest.mark.asyncio
async def test_cleanup_preserves_new_files(tmp_path: Path) -> None:
    """Context directories within max_age_days are preserved."""
    sandboxes_root = tmp_path / "sandboxes"
    sandboxes_root.mkdir()

    user_dir = sandboxes_root / "user_test"
    user_dir.mkdir()

    session_dir = user_dir / "chat_new"
    session_dir.mkdir()

    context_dir = session_dir / ".context" / "chat_new"
    context_dir.mkdir(parents=True)
    (context_dir / "file1.txt").write_text("new content")

    scheduler = ContextCleanupScheduler(sandboxes_root, max_age_days=7)
    await scheduler._run_cleanup()

    assert context_dir.exists()
    assert (context_dir / "file1.txt").exists()


@pytest.mark.asyncio
async def test_cleanup_handles_multiple_users(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Cleanup correctly traverses multiple user directories."""
    sandboxes_root = tmp_path / "sandboxes"
    sandboxes_root.mkdir()

    old_mtime = time.time() - (10 * 86400)

    for user_id in ["user1", "user2", "user3"]:
        user_dir = sandboxes_root / user_id
        user_dir.mkdir()

        session_dir = user_dir / "chat_old"
        session_dir.mkdir()

        context_dir = session_dir / ".context" / "chat_old"
        context_dir.mkdir(parents=True)
        (context_dir / "file.txt").write_text("old")

        os.utime(context_dir, (old_mtime, old_mtime))

    scheduler = ContextCleanupScheduler(sandboxes_root, max_age_days=7)

    caplog.clear()
    with caplog.at_level(logging.INFO):
        await scheduler._run_cleanup()

    orphan_logs = [r for r in caplog.records if "CONTEXT_CLEANUP_ORPHAN" in r.message]
    assert len(orphan_logs) == 3

    completion_logs = [r for r in caplog.records if "Context cleanup completed" in r.message]
    assert len(completion_logs) == 1
    assert "3 sessions cleaned" in completion_logs[0].message


@pytest.mark.asyncio
async def test_cleanup_handles_missing_sandboxes_root(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Non-existent sandboxes_root logs debug and returns."""
    non_existent = tmp_path / "non_existent"
    scheduler = ContextCleanupScheduler(non_existent, max_age_days=7)

    caplog.clear()
    with caplog.at_level(logging.DEBUG):
        await scheduler._run_cleanup()

    debug_logs = [r for r in caplog.records if r.levelno == logging.DEBUG]
    assert any("Sandboxes root not found" in r.message for r in debug_logs)


@pytest.mark.asyncio
async def test_cleanup_handles_file_deletion_error(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """File deletion failure logs warning but continues cleaning other files."""
    sandboxes_root = tmp_path / "sandboxes"
    sandboxes_root.mkdir()

    old_mtime = time.time() - (10 * 86400)

    for i in [1, 2]:
        user_dir = sandboxes_root / f"user{i}"
        user_dir.mkdir()

        session_dir = user_dir / f"chat{i}"
        session_dir.mkdir()

        context_dir = session_dir / ".context" / f"chat{i}"
        context_dir.mkdir(parents=True)
        (context_dir / "file.txt").write_text("old")

        os.utime(context_dir, (old_mtime, old_mtime))

    import shutil

    original_rmtree = shutil.rmtree
    call_count = [0]

    def mock_rmtree(path, *args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            raise PermissionError("Simulated permission error")
        return original_rmtree(path, *args, **kwargs)

    monkeypatch.setattr("shutil.rmtree", mock_rmtree)

    scheduler = ContextCleanupScheduler(sandboxes_root, max_age_days=7)

    caplog.clear()
    with caplog.at_level(logging.WARNING):
        await scheduler._run_cleanup()

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("Failed to cleanup" in r.message for r in warnings)
    assert call_count[0] >= 2


@pytest.mark.asyncio
async def test_cleanup_no_orphaned_files(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """No expired files logs debug message."""
    sandboxes_root = tmp_path / "sandboxes"
    sandboxes_root.mkdir()

    user_dir = sandboxes_root / "user_test"
    user_dir.mkdir()

    session_dir = user_dir / "chat_new"
    session_dir.mkdir()

    context_dir = session_dir / ".context" / "chat_new"
    context_dir.mkdir(parents=True)
    (context_dir / "file.txt").write_text("new")

    scheduler = ContextCleanupScheduler(sandboxes_root, max_age_days=7)

    caplog.clear()
    with caplog.at_level(logging.DEBUG):
        await scheduler._run_cleanup()

    debug_logs = [r for r in caplog.records if r.levelno == logging.DEBUG]
    assert any("no orphaned files found" in r.message for r in debug_logs)


@pytest.mark.asyncio
async def test_cleanup_handles_non_directory_files(tmp_path: Path) -> None:
    """Non-directory files in sandboxes_root are skipped."""
    sandboxes_root = tmp_path / "sandboxes"
    sandboxes_root.mkdir()

    (sandboxes_root / "random_file.txt").write_text("test")

    user_dir = sandboxes_root / "user_test"
    user_dir.mkdir()

    session_dir = user_dir / "chat_old"
    session_dir.mkdir()

    context_dir = session_dir / ".context" / "chat_old"
    context_dir.mkdir(parents=True)
    (context_dir / "file.txt").write_text("old")

    old_mtime = time.time() - (10 * 86400)
    os.utime(context_dir, (old_mtime, old_mtime))

    scheduler = ContextCleanupScheduler(sandboxes_root, max_age_days=7)
    await scheduler._run_cleanup()

    assert (sandboxes_root / "random_file.txt").exists()
    assert not context_dir.exists()


@pytest.mark.asyncio
async def test_scheduler_start_stop_lifecycle(tmp_path: Path) -> None:
    """ContextCleanupScheduler start/stop lifecycle works correctly."""
    sandboxes_root = tmp_path / "sandboxes"
    sandboxes_root.mkdir()

    scheduler = ContextCleanupScheduler(sandboxes_root, interval_hours=1)

    assert not scheduler.is_running

    scheduler.start()
    await asyncio.sleep(0.05)
    assert scheduler.is_running

    await scheduler.stop()
    assert not scheduler.is_running


@pytest.mark.asyncio
async def test_scheduler_double_start_is_noop(tmp_path: Path) -> None:
    """Starting an already-running scheduler is a no-op."""
    sandboxes_root = tmp_path / "sandboxes"
    sandboxes_root.mkdir()

    scheduler = ContextCleanupScheduler(sandboxes_root, interval_hours=1)
    scheduler.start()
    await asyncio.sleep(0.05)

    task_before = scheduler._task
    scheduler.start()
    assert scheduler._task is task_before

    await scheduler.stop()


@pytest.mark.asyncio
async def test_scheduler_stop_when_not_running(tmp_path: Path) -> None:
    """Stopping a non-running scheduler is safe."""
    sandboxes_root = tmp_path / "sandboxes"
    sandboxes_root.mkdir()

    scheduler = ContextCleanupScheduler(sandboxes_root, interval_hours=1)
    await scheduler.stop()
    assert not scheduler.is_running


@pytest.mark.asyncio
async def test_cleanup_edge_case_exactly_max_age(tmp_path: Path) -> None:
    """Files under max_age_days are preserved, over are deleted."""
    sandboxes_root = tmp_path / "sandboxes"
    sandboxes_root.mkdir()

    user_dir1 = sandboxes_root / "user_test1"
    user_dir1.mkdir()
    session_dir1 = user_dir1 / "chat_under"
    session_dir1.mkdir()
    context_dir1 = session_dir1 / ".context" / "chat_under"
    context_dir1.mkdir(parents=True)
    (context_dir1 / "file.txt").write_text("under threshold")
    under_mtime = time.time() - (6.9 * 86400)
    os.utime(context_dir1, (under_mtime, under_mtime))

    user_dir2 = sandboxes_root / "user_test2"
    user_dir2.mkdir()
    session_dir2 = user_dir2 / "chat_over"
    session_dir2.mkdir()
    context_dir2 = session_dir2 / ".context" / "chat_over"
    context_dir2.mkdir(parents=True)
    (context_dir2 / "file.txt").write_text("over threshold")
    over_mtime = time.time() - (7.1 * 86400)
    os.utime(context_dir2, (over_mtime, over_mtime))

    scheduler = ContextCleanupScheduler(sandboxes_root, max_age_days=7)
    await scheduler._run_cleanup()

    assert context_dir1.exists()
    assert not context_dir2.exists()


@pytest.mark.asyncio
async def test_cleanup_multiple_sessions_per_user(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Multiple sessions under one user are all cleaned correctly."""
    sandboxes_root = tmp_path / "sandboxes"
    sandboxes_root.mkdir()

    old_mtime = time.time() - (10 * 86400)

    user_dir = sandboxes_root / "user_alice"
    user_dir.mkdir()

    for i in [1, 2, 3]:
        session_dir = user_dir / f"chat_{i}"
        session_dir.mkdir()

        context_dir = session_dir / ".context" / f"chat_{i}"
        context_dir.mkdir(parents=True)
        (context_dir / "file.txt").write_text("old")

        os.utime(context_dir, (old_mtime, old_mtime))

    scheduler = ContextCleanupScheduler(sandboxes_root, max_age_days=7)

    caplog.clear()
    with caplog.at_level(logging.INFO):
        await scheduler._run_cleanup()

    orphan_logs = [r for r in caplog.records if "CONTEXT_CLEANUP_ORPHAN" in r.message]
    assert len(orphan_logs) == 3
