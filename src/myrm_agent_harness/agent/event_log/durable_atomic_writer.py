"""Durable atomic writer with short-write defense, advisory locking, and fsync.

Hardens event log persistence against system crashes, short writes, and
cross-process append collisions. Integrates with torn_tail_repairer to guarantee
that uncommitted garbage is truncated before new records are appended.

[INPUT]
- pathlib.Path: File path to append events to
- torn_tail_repairer::repair_torn_tail: Atomic tail self-repair hook

[OUTPUT]
- loop_write_all: Write loop ensuring entire payload reaches kernel buffer
- DurableLogWriter: Durable append manager with repair-before-append guarantee
"""

from __future__ import annotations

import contextlib
import logging
import os
from pathlib import Path
from typing import IO

from .torn_tail_repairer import repair_torn_tail

logger = logging.getLogger(__name__)

# Try importing fcntl for POSIX file locking
try:
    import fcntl
    _HAS_FCNTL = True
except ImportError:
    _HAS_FCNTL = False


def loop_write_all(fd: int, payload: bytes) -> int:
    """Loop os.write until the entire payload is committed to the OS file buffer.

    Protects against short writes that can occur during system pressure
    or non-blocking/interrupted syscalls.

    Args:
        fd: Open OS file descriptor.
        payload: Binary data to write completely.

    Returns:
        Total bytes written.

    Raises:
        OSError: If an unrecoverable IO error occurs.
    """
    total = len(payload)
    written = 0
    while written < total:
        try:
            chunk_size = os.write(fd, payload[written:])
            if chunk_size == 0:
                raise OSError("write returned 0 bytes before payload was fully written")
            written += chunk_size
        except InterruptedError:
            continue
    return written


class DurableLogWriter:
    """Manages crash-resilient append operations to an event log file.

    Features:
    1. Tail self-repair before every append batch to eliminate torn tails.
    2. Short-write loop to guarantee all bytes are written.
    3. Flushes and executes fsync when durable=True.
    4. Advisory file locking across processes when lock_file=True.
    """

    def __init__(
        self,
        file_path: Path,
        *,
        durable: bool = True,
        use_file_lock: bool = True,
    ) -> None:
        self._file_path = file_path
        self._durable = durable
        self._use_file_lock = use_file_lock and _HAS_FCNTL

    @property
    def file_path(self) -> Path:
        return self._file_path

    @contextlib.contextmanager
    def _advisory_lock(self, fd: int) -> None:
        if self._use_file_lock and _HAS_FCNTL:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                yield
            finally:
                with contextlib.suppress(OSError):
                    fcntl.flock(fd, fcntl.LOCK_UN)
        else:
            yield

    def append_payload(self, payload: bytes) -> int:
        """Atomically repair any torn tail and append the binary payload.

        Args:
            payload: UTF-8 encoded bytes to append, typically ending in newline.

        Returns:
            Number of bytes written.
        """
        if not payload:
            return 0

        self._file_path.parent.mkdir(parents=True, exist_ok=True)

        # Open in read-write-create mode to enable locking and repair in the same handle
        flags = os.O_RDWR | os.O_CREAT
        fd = os.open(self._file_path, flags, 0o644)
        try:
            with self._advisory_lock(fd):
                # 1. Self-repair any uncommitted torn tail before writing new data
                repair_torn_tail(self._file_path)

                # 2. Seek to clean end of file
                os.lseek(fd, 0, os.SEEK_END)

                # 3. Loop write until entire payload is on disk
                written = loop_write_all(fd, payload)

                # 4. Enforce physical durability if configured
                if self._durable:
                    os.fsync(fd)

                return written
        finally:
            os.close(fd)

    def append_lines(self, lines: list[str]) -> int:
        """Convenience method to encode and append string lines.

        Args:
            lines: List of string lines (each ending in '\\n').

        Returns:
            Number of bytes written.
        """
        if not lines:
            return 0
        raw_payload = "".join(lines).encode("utf-8")
        return self.append_payload(raw_payload)
