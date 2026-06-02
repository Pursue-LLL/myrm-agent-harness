"""Transparent decompression for context files.

Provides utilities to read compressed context files (.gz) transparently,
automatically handling decompression when needed.

[INPUT]
- (none)

[OUTPUT]
- TransparentFileReader: File reader with transparent decompression support.
- read_context_file_async: Read context file with transparent decompression support.
- read_context_file_sync: Read context file with transparent decompression support ...

[POS]
Transparent decompression for context files.
"""

from __future__ import annotations

import asyncio
import gzip
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


async def read_context_file_async(file_path: str | Path) -> str:
    """Read context file with transparent decompression support.

    Automatically detects and decompresses .gz files.
    Also records file access for lifecycle management.

    Args:
        file_path: Path to file (can be .gz or plain text)

    Returns:
        File content as string

    Raises:
        FileNotFoundError: If file doesn't exist
        OSError: If read operation fails

    Examples:
        >>> content = await read_context_file_async("/persistent/.context/chat_abc/compacted/tool_output.txt.gz")
        >>> # Returns decompressed content
    """
    file_path = Path(file_path)

    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    try:
        # Track file access for lifecycle management
        from myrm_agent_harness.runtime.execution_paths import (
            track_context_file_access_if_needed,
        )

        await track_context_file_access_if_needed(str(file_path))

        if file_path.suffix == ".gz":
            loop = asyncio.get_running_loop()
            content_bytes = await loop.run_in_executor(
                None,
                _read_gzip_file_sync,
                file_path,
            )
            return content_bytes.decode("utf-8")
        else:
            return await _read_text_file_async(file_path)
    except Exception as exc:
        logger.error(f"Failed to read context file {file_path}: {exc}")
        raise


def _read_gzip_file_sync(file_path: Path) -> bytes:
    """Read and decompress gzip file (sync operation for executor).

    Args:
        file_path: Path to .gz file

    Returns:
        Decompressed bytes
    """
    with gzip.open(file_path, "rb") as f:
        return f.read()


async def _read_text_file_async(file_path: Path) -> str:
    """Read plain text file asynchronously.

    Args:
        file_path: Path to text file

    Returns:
        File content as string
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        file_path.read_text,
        "utf-8",
    )


def read_context_file_sync(file_path: str | Path) -> str:
    """Read context file with transparent decompression support (sync version).

    Automatically detects and decompresses .gz files.

    Note: This is synchronous and cannot track file access (requires async).
    For tracking, use read_context_file_async or call tracking separately.

    Args:
        file_path: Path to file (can be .gz or plain text)

    Returns:
        File content as string

    Raises:
        FileNotFoundError: If file doesn't exist
        OSError: If read operation fails

    Examples:
        >>> content = read_context_file_sync("/persistent/.context/chat_abc/compacted/tool_output.txt.gz")
        >>> # Returns decompressed content
    """
    file_path = Path(file_path)

    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    try:
        if file_path.suffix == ".gz":
            with gzip.open(file_path, "rt", encoding="utf-8") as f:
                return f.read()
        else:
            return file_path.read_text(encoding="utf-8")
    except Exception as exc:
        logger.error(f"Failed to read context file {file_path}: {exc}")
        raise


class TransparentFileReader:
    """File reader with transparent decompression support.

    Provides both sync and async interfaces for reading context files,
    automatically handling .gz decompression.

    Usage:
        >>> reader = TransparentFileReader()
        >>> content = await reader.read_async("/persistent/.context/chat_abc/file.txt.gz")
        >>> # or
        >>> content = reader.read_sync("/persistent/.context/chat_abc/file.txt")
    """

    async def read_async(self, file_path: str | Path) -> str:
        """Read file asynchronously with transparent decompression.

        Args:
            file_path: Path to file

        Returns:
            File content as string
        """
        return await read_context_file_async(file_path)

    def read_sync(self, file_path: str | Path) -> str:
        """Read file synchronously with transparent decompression.

        Args:
            file_path: Path to file

        Returns:
            File content as string
        """
        return read_context_file_sync(file_path)

    def is_compressed(self, file_path: str | Path) -> bool:
        """Check if file is compressed.

        Args:
            file_path: Path to file

        Returns:
            True if file is .gz compressed
        """
        return Path(file_path).suffix == ".gz"
