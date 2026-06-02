"""Atomic file write with crash-consistency guarantee.

Writes content to a file via tmpfile + fsync + atomic rename, ensuring:
- No partial/truncated files on process crash
- No data loss on power failure (fsync flushes to disk)
- No name collision under concurrent processes (mkstemp)

Usage::

    from myrm_agent_harness.infra.atomic_write import atomic_write, async_atomic_write

    atomic_write(path, json.dumps(data))                     # sync
    await async_atomic_write(path, json.dumps(data))         # async
    atomic_write(path, binary_content, mode=None)             # no chmod

[INPUT]
- (none)

[OUTPUT]
- atomic_write: Atomically write content to a file.
- async_atomic_write: Async wrapper around :func:`atomic_write` via ``asyncio.t...

[POS]
Atomic file write with crash-consistency guarantee.
"""

import asyncio
import contextlib
import os
import tempfile
from pathlib import Path


def atomic_write(
    path: str | Path,
    content: str | bytes,
    *,
    mode: int | None = 0o600,
) -> None:
    """Atomically write content to a file.

    Args:
        path: Target file path.
        content: Text (str) or binary (bytes) content to write.
        mode: File permission bits (default 0o600). Pass None to skip chmod.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    is_text = isinstance(content, str)
    fd = -1
    tmp_path: str | None = None

    try:
        fd, tmp_path = tempfile.mkstemp(dir=target.parent, prefix=".atomic_")

        with os.fdopen(fd, "w" if is_text else "wb", **({"encoding": "utf-8"} if is_text else {})) as f:
            fd = -1  # fdopen takes ownership
            f.write(content)
            f.flush()
            os.fsync(f.fileno())

        if mode is not None:
            os.chmod(tmp_path, mode)

        os.replace(tmp_path, target)
        tmp_path = None  # replaced successfully, no cleanup needed

        # fsync parent directory to ensure rename is durable on ext4/XFS
        try:
            dir_fd = os.open(str(target.parent), os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass  # Windows/special FS reject directory fds — safe to ignore

    finally:
        if fd >= 0:
            os.close(fd)
        if tmp_path is not None:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)


async def async_atomic_write(
    path: str | Path,
    content: str | bytes,
    *,
    mode: int | None = 0o600,
) -> None:
    """Async wrapper around :func:`atomic_write` via ``asyncio.to_thread``."""
    await asyncio.to_thread(atomic_write, path, content, mode=mode)
