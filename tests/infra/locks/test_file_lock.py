"""Tests for FileLock."""

import asyncio
import os
import stat
from pathlib import Path
from unittest import mock

import pytest

from myrm_agent_harness.infra.locks import file_lock as file_lock_module
from myrm_agent_harness.infra.locks.file_lock import (
    FileLock,
    _sanitize_lock_key,
    acquire_file_lock,
)


@pytest.mark.asyncio
async def test_file_lock_success(tmp_path):
    lock = FileLock(tmp_path)

    async with lock.acquire("res1") as acquired:
        assert acquired is True
        assert (tmp_path / "res1.lock").exists()

    # Lock file should be removed
    assert not (tmp_path / "res1.lock").exists()


@pytest.mark.asyncio
async def test_file_lock_contention(tmp_path):
    lock1 = FileLock(tmp_path)
    lock2 = FileLock(tmp_path)

    async with lock1.acquire("res_contended") as acq1:
        assert acq1 is True

        # Second lock attempt should fail (non-blocking)
        async with lock2.acquire("res_contended") as acq2:
            assert acq2 is False


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
    finally:
        # Restore permissions for cleanup
        os.chmod(ro_dir, stat.S_IRWXU)


@pytest.mark.asyncio
async def test_blocking_mode_rejected(tmp_path):
    """blocking=True is rejected with TypeError to avoid freezing the loop."""
    lock = FileLock(tmp_path)

    with pytest.raises(TypeError):
        async with lock.acquire("res_blocking", blocking=True):
            pass


@pytest.mark.asyncio
async def test_acquire_file_lock_helper(tmp_path):
    async with acquire_file_lock("helper_res", tmp_path) as acquired:
        assert acquired is True
        assert (tmp_path / "helper_res.lock").exists()

    assert not (tmp_path / "helper_res.lock").exists()


def test_sanitize_lock_key_keeps_safe_chars():
    assert _sanitize_lock_key("res-1_2") == "res-1_2"


def test_sanitize_lock_key_replaces_unsafe_chars():
    # '/', '.', '..' all collapse to '_' — no path separators or hidden files
    assert _sanitize_lock_key("res/../evil") == "res____evil"
    assert _sanitize_lock_key("../../escape") == "______escape"
    assert _sanitize_lock_key("///") == "___"
    assert _sanitize_lock_key("") == "_"


def test_sanitize_lock_key_truncates_long_keys():
    long_key = "k" * 500
    sanitized = _sanitize_lock_key(long_key)
    assert len(sanitized) == 128
    # Readable prefix is preserved and a short hash suffix keeps uniqueness
    assert sanitized.startswith("k" * 119)
    assert len(sanitized.rsplit("-", 1)[-1]) == 8


def test_sanitize_lock_key_distinct_when_truncated():
    # Two long keys sharing a prefix keep distinct hashes after truncation
    a = _sanitize_lock_key("shared" * 50 + "aaa")
    b = _sanitize_lock_key("shared" * 50 + "bbb")
    assert a != b


def test_sanitize_lock_key_unicode_replaced():
    """Non-ASCII characters (CJK/emoji) collapse to '_', staying filesystem-safe."""
    assert _sanitize_lock_key("消息-1") == "__-1"
    assert _sanitize_lock_key("📦id") == "_id"


def test_sanitized_key_cannot_escape_lock_dir(tmp_path):
    """Path traversal via resource_id must stay inside lock_dir."""
    lock = FileLock(tmp_path)
    seen_paths: list[Path] = []

    async def _exercise():
        async with lock.acquire("../../escape") as acquired:
            assert acquired is True
            seen_paths.extend(tmp_path.glob("*.lock"))

    asyncio.run(_exercise())

    # The lock file was created inside lock_dir (not escaped), then removed
    assert len(seen_paths) == 1
    assert seen_paths[0].parent == tmp_path
    assert seen_paths[0].name == "______escape.lock"


@pytest.mark.asyncio
async def test_file_lock_propagates_body_exception(tmp_path):
    """Exceptions raised inside the lock body must propagate unchanged —
    the lock machinery must not swallow them — and the lock must still be
    released so the resource is re-acquirable."""
    lock = FileLock(tmp_path)

    class DeliveryError(Exception):
        pass

    with pytest.raises(DeliveryError):
        async with lock.acquire("res_body_err") as acquired:
            assert acquired is True
            raise DeliveryError("delivery failed")

    assert not (tmp_path / "res_body_err.lock").exists()

    async with lock.acquire("res_body_err") as acquired:
        assert acquired is True


@pytest.mark.asyncio
async def test_invalid_mode_rejected(tmp_path):
    """Unrecognized mode must fail fast with ValueError instead of silently
    downgrading an exclusive lock to a shared one."""
    lock = FileLock(tmp_path)

    with pytest.raises(ValueError):
        async with lock.acquire("res_bad_mode", mode="exclusiv"):
            pass


@pytest.mark.asyncio
async def test_unlock_failure_cleans_up(tmp_path):
    """An OSError while releasing the lock must not leak the file handle or
    leave a stale lock file behind."""
    lock = FileLock(tmp_path)

    with mock.patch.object(
        file_lock_module.fcntl,
        "flock",
        autospec=True,
        side_effect=[None, OSError("release failed")],
    ):
        async with lock.acquire("res_unlock_fail") as acquired:
            assert acquired is True

    assert not (tmp_path / "res_unlock_fail.lock").exists()


@pytest.mark.asyncio
async def test_close_failure_still_unlinks(tmp_path):
    """An OSError while closing the lock file must still remove the lock file
    so the resource stays re-acquirable."""
    lock = FileLock(tmp_path)
    real_open = open

    class _CloseFailsFile:
        def __init__(self, handle):
            self._handle = handle

        def fileno(self):
            return self._handle.fileno()

        def close(self):
            raise OSError("close failed")

    with mock.patch(
        "myrm_agent_harness.infra.locks.file_lock.open",
        side_effect=lambda path, *a, **kw: _CloseFailsFile(real_open(path, *a, **kw)),
    ):
        async with lock.acquire("res_close_fail") as acquired:
            assert acquired is True

    assert not (tmp_path / "res_close_fail.lock").exists()


@pytest.mark.asyncio
async def test_unlink_failure_logged_and_locked(tmp_path):
    """An OSError while unlinking the lock file must be contained: the caller
    gets a successful acquisition and the lock itself remains held."""
    lock = FileLock(tmp_path)
    lock_file = tmp_path / "res_unlink_fail.lock"

    with mock.patch.object(
        Path, "unlink", side_effect=OSError("unlink failed")
    ) as mock_unlink:
        async with lock.acquire("res_unlink_fail") as acquired:
            assert acquired is True
            assert lock_file.exists()

    mock_unlink.assert_called_once()
    assert lock_file.exists()


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.name == "nt",
    reason="Creating symlinks on Windows typically requires elevated privileges",
)
async def test_symlink_lock_rejected(tmp_path):
    """A symlink planted in the lock directory must be rejected (O_NOFOLLOW):
    acquisition returns False and the file the symlink points at stays intact."""
    lock = FileLock(tmp_path)
    victim = tmp_path / "victim.txt"
    victim.write_text("precious-data")

    symlink = tmp_path / "res_symlink.lock"
    symlink.symlink_to(victim)

    async with lock.acquire("res_symlink") as acquired:
        assert acquired is False

    assert victim.read_text() == "precious-data"
    assert symlink.is_symlink()
