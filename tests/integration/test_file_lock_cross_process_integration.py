"""Integration tests: FileLock cross-process mutual exclusion and crash recovery.

These tests prove the OS-level guarantees the lock's docs promise:
- an exclusive lock is visible across processes (fcntl.flock is per inode);
- when a process holding a lock dies hard, the kernel releases the lock so the
  resource becomes immediately re-acquirable (recovery path on sandbox restart).

A fresh interpreter (``sys.executable``) is used for the remote holder instead
of ``multiprocessing``: forking a live asyncio event loop is unsafe on macOS
and would deadlock the suite.
"""

import asyncio
import contextlib
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from typing import Literal

import pytest

from myrm_agent_harness.infra.locks.file_lock import FileLock

_HOLDER_SCRIPT = textwrap.dedent(
    """
    import asyncio
    import os
    import sys
    from pathlib import Path

    from myrm_agent_harness.infra.locks.file_lock import FileLock

    lock_dir, resource_id, mode, ready_file = sys.argv[1:]

    async def main() -> None:
        lock = FileLock(Path(lock_dir))
        async with lock.acquire(resource_id, mode=mode) as acquired:
            if not acquired:
                os._exit(3)
            Path(ready_file).touch()
            await asyncio.sleep(600)

    asyncio.run(main())
    """
)


class _RemoteHolder:
    """Holds a FileLock in a child interpreter until killed."""

    def __init__(self, lock_dir: Path, resource_id: str, *, mode: str) -> None:
        self.lock_dir = lock_dir
        self.resource_id = resource_id
        self.mode = mode
        self.ready_file = lock_dir / f"{resource_id}.ready"
        self._proc: subprocess.Popen[str] | None = None

    def __enter__(self) -> "_RemoteHolder":
        self.ready_file.unlink(missing_ok=True)
        self._proc = subprocess.Popen(
            [
                sys.executable,
                "-c",
                _HOLDER_SCRIPT,
                str(self.lock_dir),
                self.resource_id,
                self.mode,
                str(self.ready_file),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self.ready_file.exists():
                return self
            if self._proc.poll() is not None:
                raise RuntimeError("holder process exited before acquiring the lock")
            time.sleep(0.05)
        raise RuntimeError("timed out waiting for holder to acquire the lock")

    def __exit__(self, *_exc: object) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.kill()
            with contextlib.suppress(subprocess.TimeoutExpired):
                self._proc.wait(timeout=10)


def _local_acquire(lock_dir: Path, resource_id: str, *, mode: Literal["exclusive", "shared"] = "exclusive") -> bool:
    lock = FileLock(lock_dir)

    async def _acquire() -> bool:
        async with lock.acquire(resource_id, mode=mode) as acquired:
            return acquired

    return asyncio.run(_acquire())


@pytest.mark.integration
def test_exclusive_lock_blocks_other_process(tmp_path: Path) -> None:
    """A lock held in another process must block this process."""
    lock_dir = tmp_path / "locks"
    lock_dir.mkdir()
    with _RemoteHolder(lock_dir, "cross-res", mode="exclusive"):
        assert _local_acquire(lock_dir, "cross-res") is False


@pytest.mark.integration
def test_lock_auto_released_on_process_crash(tmp_path: Path) -> None:
    """After the holder hard-crashes, the kernel releases the lock and the
    resource is immediately re-acquirable."""
    lock_dir = tmp_path / "locks"
    lock_dir.mkdir()
    holder = _RemoteHolder(lock_dir, "crash-res", mode="exclusive")
    with holder:
        assert _local_acquire(lock_dir, "crash-res") is False
    holder.__exit__()

    assert _local_acquire(lock_dir, "crash-res") is True


@pytest.mark.integration
def test_shared_lock_blocks_exclusive_other_process(tmp_path: Path) -> None:
    """A shared lock held by another process must block a local exclusive
    acquisition."""
    lock_dir = tmp_path / "locks"
    lock_dir.mkdir()
    with _RemoteHolder(lock_dir, "sh-ex-res", mode="shared"):
        assert _local_acquire(lock_dir, "sh-ex-res") is False


@pytest.mark.integration
def test_shared_lock_coexists_other_process(tmp_path: Path) -> None:
    """Two processes holding the same resource in shared mode do not block."""
    lock_dir = tmp_path / "locks"
    lock_dir.mkdir()
    with _RemoteHolder(lock_dir, "sh-sh-res", mode="shared"):
        assert _local_acquire(lock_dir, "sh-sh-res", mode="shared") is True
