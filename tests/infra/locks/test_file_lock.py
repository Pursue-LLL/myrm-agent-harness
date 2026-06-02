"""Tests for FileLock."""

import os
import stat

import pytest

from myrm_agent_harness.infra.locks.file_lock import (
    FileLock,
    LockMetrics,
    acquire_file_lock,
)


def test_lock_metrics():
    metrics = LockMetrics()
    assert metrics.success_rate == 0.0
    assert metrics.avg_wait_time_ms == 0.0

    metrics.record_attempt()
    metrics.record_acquired(10.0)
    assert metrics.success_rate == 1.0
    assert metrics.avg_wait_time_ms == 10.0

    metrics.record_attempt()
    metrics.record_failed()
    assert metrics.success_rate == 0.5

    metrics.record_error()
    assert metrics.lock_errors == 1

    d = metrics.to_dict()
    assert d["lock_attempts"] == 2
    assert d["lock_acquired"] == 1
    assert d["lock_failed"] == 1

@pytest.mark.asyncio
async def test_file_lock_success(tmp_path):
    lock = FileLock(tmp_path)

    async with lock.acquire("res1") as acquired:
        assert acquired is True
        assert (tmp_path / "res1.lock").exists()

    # Lock file should be removed
    assert not (tmp_path / "res1.lock").exists()

    metrics = lock.get_metrics()
    assert metrics["lock_attempts"] == 1
    assert metrics["lock_acquired"] == 1

@pytest.mark.asyncio
async def test_file_lock_contention(tmp_path):
    lock1 = FileLock(tmp_path)
    lock2 = FileLock(tmp_path)

    async with lock1.acquire("res_contended") as acq1:
        assert acq1 is True

        # Second lock attempt should fail (non-blocking)
        async with lock2.acquire("res_contended", blocking=False) as acq2:
            assert acq2 is False

    assert lock2.metrics.lock_failed == 1

@pytest.mark.asyncio
async def test_file_lock_shared(tmp_path):
    lock1 = FileLock(tmp_path)
    lock2 = FileLock(tmp_path)

    # Shared locks should not block each other
    async with lock1.acquire("res_shared", mode="shared") as acq1:
        assert acq1 is True

        async with lock2.acquire("res_shared", mode="shared") as acq2:
            assert acq2 is True

@pytest.mark.asyncio
async def test_file_lock_error_handling(tmp_path):
    # Create a read-only directory
    ro_dir = tmp_path / "ro"
    ro_dir.mkdir()
    os.chmod(ro_dir, stat.S_IRUSR | stat.S_IXUSR)

    try:
        lock = FileLock(ro_dir)
        async with lock.acquire("res_err") as acquired:
            assert acquired is False

        assert lock.metrics.lock_errors == 1
    finally:
        # Restore permissions for cleanup
        os.chmod(ro_dir, stat.S_IRWXU)

@pytest.mark.asyncio
async def test_acquire_file_lock_helper(tmp_path):
    async with acquire_file_lock("helper_res", tmp_path) as acquired:
        assert acquired is True
        assert (tmp_path / "helper_res.lock").exists()

    assert not (tmp_path / "helper_res.lock").exists()

def test_reset_metrics(tmp_path):
    lock = FileLock(tmp_path)
    lock.metrics.record_attempt()
    assert lock.metrics.lock_attempts == 1

    lock.reset_metrics()
    assert lock.metrics.lock_attempts == 0

def test_disable_metrics(tmp_path):
    lock = FileLock(tmp_path, enable_metrics=False)
    assert lock.metrics is None
    assert lock.get_metrics() is None

    # Operations should not crash when metrics are disabled
    lock.reset_metrics()
