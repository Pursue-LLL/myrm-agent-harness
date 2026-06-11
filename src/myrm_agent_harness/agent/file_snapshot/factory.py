"""File snapshot store factory.

Selects the best available snapshot store implementation:
- ShadowGitSnapshotStore when git is available (preferred: deduplication, isolation)
- LocalFileSnapshotStore when git is absent (fallback: file copy)

Both implementations conform to FileSnapshotProtocol.

[POS]
Factory for creating file snapshot store instances with automatic git detection.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from myrm_agent_harness.utils.logger_utils import get_agent_logger

from .local_store import LocalFileSnapshotStore
from .protocols import FileSnapshotProtocol
from .shadow_git_store import ShadowGitSnapshotStore

logger = get_agent_logger(__name__)


def _default_store_base() -> Path:
    """Resolve the base directory for file snapshot storage."""
    data_dir = os.environ.get("MYRM_DATA_DIR", "").strip()
    if data_dir:
        return Path(data_dir) / "file_snapshots"
    return Path.home() / ".myrm" / "file_snapshots"


async def _detect_git() -> bool:
    """One-time probe for system git availability."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "--version",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.communicate()
        return proc.returncode == 0
    except FileNotFoundError:
        return False


_cached_store: FileSnapshotProtocol | None = None


async def create_file_snapshot_store() -> FileSnapshotProtocol:
    """Create the best available file snapshot store.

    Uses ShadowGitSnapshotStore when git is available (preferred),
    falls back to LocalFileSnapshotStore otherwise.

    The result is cached for the process lifetime.
    """
    global _cached_store
    if _cached_store is not None:
        return _cached_store

    base_path = _default_store_base()

    if await _detect_git():
        logger.info("Git available — using ShadowGitSnapshotStore at %s", base_path)
        _cached_store = ShadowGitSnapshotStore(store_path=base_path)
    else:
        logger.info("Git not found — using LocalFileSnapshotStore at %s", base_path / "local")
        _cached_store = LocalFileSnapshotStore(storage_path=base_path / "local")

    return _cached_store


def get_cached_store() -> FileSnapshotProtocol | None:
    """Get the cached store instance, or None if not yet created."""
    return _cached_store
