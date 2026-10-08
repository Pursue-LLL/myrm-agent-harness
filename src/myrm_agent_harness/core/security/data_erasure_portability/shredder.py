"""Physical storage file shredder adhering to NIST SP 800-88 and DoD 5220.22-M."""

from __future__ import annotations

import contextlib
import logging
import os
from pathlib import Path

from myrm_agent_harness.core.security.data_erasure_portability.types import (
    ShreddingPassConfig,
)

logger = logging.getLogger(__name__)


class SecureStorageShredder:
    """Multi-pass physical file shredder executing deterministic overwrite sequences."""

    def __init__(self, default_config: ShreddingPassConfig | None = None) -> None:
        self._config = default_config or ShreddingPassConfig()

    def shred_bytes_buffer(self, buffer: bytearray) -> None:
        """Securely zero-out and randomize a mutable bytearray in memory."""
        length = len(buffer)
        if length == 0:
            return
        # Pass 1: Zero
        buffer[:] = b"\x00" * length
        # Pass 2: Ones
        buffer[:] = b"\xff" * length
        # Pass 3: Random
        buffer[:] = os.urandom(length)
        # Final: Zero
        buffer[:] = b"\x00" * length

    def shred_file(
        self,
        file_path: Path | str,
        config: ShreddingPassConfig | None = None,
    ) -> int:
        """Shred a single file using multi-pass overwrites, sync, and unlink.

        Returns:
            Total shredded bytes count.
        """
        cfg = config or self._config
        path = Path(file_path).resolve()
        if not path.is_file():
            return 0

        file_size = path.stat().st_size
        if file_size == 0:
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning("Failed to unlink empty file %s: %s", path, exc)
            return 0

        try:
            with open(path, "r+b") as f:
                fd = f.fileno()
                passes = cfg.passes
                for p in range(passes):
                    f.seek(0)
                    if p % 3 == 0:
                        data = b"\x00" * min(file_size, 65536)
                    elif p % 3 == 1:
                        data = b"\xff" * min(file_size, 65536)
                    else:
                        data = os.urandom(min(file_size, 65536))

                    written = 0
                    while written < file_size:
                        chunk = data[: file_size - written]
                        f.write(chunk)
                        written += len(chunk)

                    if cfg.flush_sync:
                        f.flush()
                        os.fsync(fd)

                # Truncate to 0 before unlinking
                f.truncate(0)
                if cfg.flush_sync:
                    f.flush()
                    os.fsync(fd)

            path.unlink(missing_ok=True)
            logger.info("Securely shredded file: %s (%d bytes)", path, file_size)
            return file_size
        except OSError as exc:
            logger.error("OS error shredding file %s: %s", path, exc)
            return 0

    def shred_directory(
        self,
        directory_path: Path | str,
        config: ShreddingPassConfig | None = None,
    ) -> tuple[int, int]:
        """Recursively shred all files within a directory and remove empty directory tree.

        Returns:
            Tuple of (total_files_shredded, total_bytes_shredded).
        """
        target_dir = Path(directory_path).resolve()
        if not target_dir.is_dir():
            return (0, 0)

        total_bytes = 0
        total_files = 0

        # Collect all files first
        all_files: list[Path] = [p for p in target_dir.rglob("*") if p.is_file()]
        for file_p in all_files:
            b = self.shred_file(file_p, config=config)
            total_bytes += b
            total_files += 1

        # Remove empty directories in reverse traversal order
        all_dirs: list[Path] = sorted(
            [d for d in target_dir.rglob("*") if d.is_dir()],
            key=lambda p: len(p.parts),
            reverse=True,
        )
        for d in all_dirs:
            with contextlib.suppress(OSError):
                d.rmdir()

        with contextlib.suppress(OSError):
            target_dir.rmdir()

        return (total_files, total_bytes)
