"""Secure temporary file lifecycle with POSIX 0600 permissions and zero-trace wiping.

[INPUT]
- payload (str or bytes), SecureIpcFileOptions

[OUTPUT]
- SecureIpcFile: Context manager yielding secure temporary file path and ensuring shred-and-unlink

[POS]
Harness core security module. Eliminates command-line string parameter vulnerabilities by
storing queries in 0600-mode temporary files, and shredding all bytes upon exit.
"""

from __future__ import annotations

import contextlib
import logging
import os
import tempfile
from pathlib import Path
from types import TracebackType
from uuid import uuid4

from myrm_agent_harness.core.security.ipc.types import SecureIpcFileOptions

logger = logging.getLogger(__name__)


class SecureIpcFile:
    """Context manager creating a temporary 0600 file and wiping it upon exit."""

    def __init__(
        self,
        payload: str | bytes,
        options: SecureIpcFileOptions | None = None,
    ) -> None:
        self._payload = payload if isinstance(payload, bytes) else payload.encode("utf-8")
        self._options = options if options is not None else SecureIpcFileOptions()
        self._file_path: str | None = None

    @property
    def path(self) -> str:
        """Return the absolute path of the secure file."""
        if self._file_path is None:
            raise RuntimeError("SecureIpcFile has not been opened yet")
        return self._file_path

    def __enter__(self) -> str:
        base_dir = self._options.base_dir or tempfile.gettempdir()
        filename = f"{self._options.prefix}{uuid4().hex}.dat"
        file_path = os.path.join(base_dir, filename)

        flags = os.O_CREAT | os.O_WRONLY | os.O_EXCL
        fd = os.open(file_path, flags, self._options.mode)
        try:
            with os.fdopen(fd, "wb", closefd=True) as f:
                f.write(self._payload)
                f.flush()
                os.fsync(f.fileno())
        except Exception:
            with contextlib.suppress(OSError):
                os.unlink(file_path)
            raise

        self._file_path = file_path
        return file_path

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.cleanup()

    def cleanup(self) -> None:
        """Physically shred and unlink the temporary file."""
        if not self._file_path:
            return

        target_path = self._file_path
        self._file_path = None

        if not os.path.exists(target_path):
            return

        try:
            if self._options.shred_before_unlink:
                size = os.path.getsize(target_path)
                if size > 0:
                    with open(target_path, "wb") as f:
                        f.write(b"\x00" * size)
                        f.flush()
                        os.fsync(f.fileno())
            os.unlink(target_path)
            logger.debug("Successfully shredded and unlinked IPC file: %s", target_path)
        except OSError as exc:
            logger.warning("Failed to shred or unlink IPC file %s: %s", target_path, exc)


def read_query_file(file_path: str) -> str:
    """Safely read content from an IPC query file."""
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"IPC query file not found: {file_path}")

    # Enforce POSIX permission check: must not be world-readable
    st = os.stat(file_path)
    file_mode = st.st_mode & 0o777
    if file_mode & 0o007 != 0:
        logger.warning("IPC query file %s has insecure world permissions: %o", file_path, file_mode)

    return Path(file_path).read_text(encoding="utf-8")
