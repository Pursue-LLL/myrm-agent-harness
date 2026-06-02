"""Storage usage monitoring for context files.

Provides real-time storage usage tracking for context offload directories.
Returns instance-level data for business layer integration.

Performance (实测数据，Python 3.13 / macOS):
    - Scan 1000 files: ~31ms
    - Memory overhead: <10MB during scan

Usage:
    ```python
    # Get storage usage for a session
    usage = get_session_storage_usage("chat_abc123")
    print(f"Total: {usage.total_bytes} bytes, Files: {usage.file_count}")

    # Get storage usage for all sessions
    total_usage = get_total_storage_usage()
    print(f"Total: {total_usage.total_bytes} bytes")

    # Business layer can push to monitoring systems
    usage_dict = {
        "total_bytes": usage.total_bytes,
        "file_count": usage.file_count,
        "compacted_files": usage.compacted_files,
        "scratchpad_files": usage.scratchpad_files,
    }
    # push_to_prometheus(usage_dict) or push_to_datadog(usage_dict)
    ```

[INPUT]
- (none)

[OUTPUT]
- StorageUsage: Storage usage statistics.
- get_session_storage_usage: Get storage usage for a specific session.
- get_total_storage_usage: Get total storage usage across all sessions.
- get_storage_usage_gb: Get storage usage in GB.

[POS]
Storage usage monitoring for context files.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from ..execution_paths import CONTEXT_ROOT

logger = logging.getLogger(__name__)


@dataclass
class StorageUsage:
    """Storage usage statistics."""

    total_bytes: int
    file_count: int
    compacted_files: int
    scratchpad_files: int


def get_session_storage_usage(session_id: str) -> StorageUsage:
    """Get storage usage for a specific session.

    Args:
        session_id: Session identifier

    Returns:
        StorageUsage with total bytes and file counts

    Note:
        Returns zero values if session directory does not exist.
    """
    session_dir = Path(CONTEXT_ROOT) / session_id

    if not session_dir.exists():
        return StorageUsage(
            total_bytes=0,
            file_count=0,
            compacted_files=0,
            scratchpad_files=0,
        )

    total_bytes = 0
    compacted_files = 0
    scratchpad_files = 0

    # Scan compacted directory
    compacted_dir = session_dir / "compacted"
    if compacted_dir.exists():
        for file_path in compacted_dir.rglob("*"):
            if file_path.is_file():
                total_bytes += file_path.stat().st_size
                compacted_files += 1

    # Scan scratchpad directory
    scratchpad_dir = session_dir / "scratchpad"
    if scratchpad_dir.exists():
        for file_path in scratchpad_dir.rglob("*"):
            if file_path.is_file():
                total_bytes += file_path.stat().st_size
                scratchpad_files += 1

    return StorageUsage(
        total_bytes=total_bytes,
        file_count=compacted_files + scratchpad_files,
        compacted_files=compacted_files,
        scratchpad_files=scratchpad_files,
    )


def get_total_storage_usage() -> StorageUsage:
    """Get total storage usage across all sessions.

    Returns:
        StorageUsage with aggregated statistics

    Note:
        Returns zero values if context root does not exist.
    """
    context_root = Path(CONTEXT_ROOT)

    if not context_root.exists():
        return StorageUsage(
            total_bytes=0,
            file_count=0,
            compacted_files=0,
            scratchpad_files=0,
        )

    total_bytes = 0
    total_files = 0
    total_compacted = 0
    total_scratchpad = 0

    # Scan all session directories
    for session_dir in context_root.iterdir():
        if not session_dir.is_dir():
            continue

        # Skip system directory
        if session_dir.name == "system":
            continue

        usage = get_session_storage_usage(session_dir.name)
        total_bytes += usage.total_bytes
        total_files += usage.file_count
        total_compacted += usage.compacted_files
        total_scratchpad += usage.scratchpad_files

    return StorageUsage(
        total_bytes=total_bytes,
        file_count=total_files,
        compacted_files=total_compacted,
        scratchpad_files=total_scratchpad,
    )


def get_storage_usage_gb(session_id: str | None = None) -> float:
    """Get storage usage in GB.

    Args:
        session_id: Session identifier (None for total across all sessions)

    Returns:
        Storage usage in GB

    Example:
        >>> get_storage_usage_gb("chat_abc123")
        0.05
        >>> get_storage_usage_gb()  # Total across all sessions
        1.23
    """
    if session_id:
        usage = get_session_storage_usage(session_id)
    else:
        usage = get_total_storage_usage()

    return usage.total_bytes / (1024**3)
