"""Cross-platform OS compatibility layer.

[INPUT]
- sys
- os
- signal
- subprocess

[OUTPUT]
- get_process_group_kwargs: Subprocess kwargs for creating process groups.
- kill_process_group: Safely kill a process group tree.
- LOCK_EX, LOCK_SH, LOCK_NB, LOCK_UN: Cross-platform lock flags.
- flock: Cross-platform fcntl.flock wrapper.
- lockf: Cross-platform fcntl.lockf wrapper.

[POS]
Provides unified abstractions for POSIX/Windows differences (file locks, process groups)
to ensure 100% native execution across all platforms.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from typing import Any

IS_WIN = sys.platform == "win32"

if IS_WIN:
    # msvcrt is a Windows-only stdlib; mypy on POSIX cannot see its members.
    import msvcrt  # type: ignore[import-not-found,unused-ignore,reportMissingImports]

    LOCK_EX = 1  # Dummy mapping
    LOCK_SH = 2
    LOCK_NB = 4
    LOCK_UN = 8

    def _win_lock(fd_or_file: Any, op: int, length: int = 1) -> None:
        fd = fd_or_file if isinstance(fd_or_file, int) else fd_or_file.fileno()
        # msvcrt.locking requires locking the current position, so we save it, seek to 0, lock, then restore
        pos = os.lseek(fd, 0, os.SEEK_CUR)
        os.lseek(fd, 0, os.SEEK_SET)

        mode = msvcrt.LK_NBLCK if (op & LOCK_NB) else msvcrt.LK_LOCK  # type: ignore[attr-defined]
        if op & LOCK_UN:
            mode = msvcrt.LK_UNLCK  # type: ignore[attr-defined]

        try:
            msvcrt.locking(fd, mode, length)  # type: ignore[attr-defined]
        except OSError as e:
            if op & LOCK_NB:
                raise BlockingIOError() from e
            raise
        finally:
            os.lseek(fd, pos, os.SEEK_SET)

    def flock(fd: Any, op: int) -> None:
        _win_lock(fd, op, 1)

    def lockf(fd: Any, op: int, length: int = 0, start: int = 0, whence: int = 0) -> None:
        # length=0 means whole file in fcntl. On Windows we lock a large number of bytes.
        # But we mostly only need 1 byte lock to coordinate inter-process for same-file locks.
        _win_lock(fd, op, length if length > 0 else 1)
else:
    import fcntl

    LOCK_EX = fcntl.LOCK_EX
    LOCK_SH = fcntl.LOCK_SH
    LOCK_NB = fcntl.LOCK_NB
    LOCK_UN = fcntl.LOCK_UN

    def flock(fd: Any, op: int) -> None:
        fcntl.flock(fd, op)

    def lockf(fd: Any, op: int, length: int = 0, start: int = 0, whence: int = 0) -> None:
        fcntl.lockf(fd, op, length, start, whence)


def get_process_group_kwargs() -> dict[str, Any]:
    """Return kwargs for subprocess.Popen / asyncio.create_subprocess_exec.

    ``Any`` is intentional: the resulting dict is unpacked into stdlib APIs
    whose parameter types are platform-specific (``creationflags`` on Win,
    ``start_new_session`` on POSIX) and otherwise refused by ``mypy`` when
    fed through ``**kwargs``.
    """
    if IS_WIN:
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 512)
        return {"creationflags": creationflags}
    return {"start_new_session": True}


def kill_process_group(pid: int, sig: int = signal.SIGKILL) -> None:
    """Kill an entire process tree/group across platforms."""
    if IS_WIN:
        # On Windows, taskkill /T /F is the most reliable way to kill a process tree
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, check=False)
    else:
        try:
            pgid = os.getpgid(pid)
            if pgid == os.getpgid(os.getpid()):
                # Safety check: do not kill our own process group!
                os.kill(pid, sig)
            else:
                os.killpg(pgid, sig)
        except (ProcessLookupError, OSError):
            pass
