"""Context file cleanup with a single retention window.

A context file is removed once nothing has read or written it for ``retention_days``:
- a recorded read (file access tracker) keeps it,
- a recent write (file modification time) keeps it,
- otherwise it is removed.

[INPUT]
- runtime.paths.execution_paths::CONTEXT_SUBDIRS, get_context_root
- runtime.context.instance_metrics::record_cleanup_phase_duration, record_protection_rule_hit, record_batch_query
- runtime.context.file_access_tracker::FileAccessTracker, get_file_access_tracker (POS: SQLite record of context file reads)

[OUTPUT]
- CONTEXT_RETENTION_DAYS: default retention window
- cleanup_context_files_async: Clean up expired context files, honouring recorded reads.
- cleanup_context_files_local: Clean up expired context files by modification time only.

[POS]
Context file cleanup. The context root is read at call time because local development rebinds it at
startup, after this module has been imported.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .file_access_tracker import FileAccessTracker

from myrm_agent_harness.runtime.paths.execution_paths import CONTEXT_SUBDIRS, get_context_root

from .instance_metrics import (
    record_batch_query,
    record_cleanup_duration,
    record_cleanup_phase_duration,
    record_protection_rule_hit,
    record_tracker_statistics,
)

CONTEXT_RETENTION_DAYS = 14

_CLEANABLE_SUBDIRS = list(CONTEXT_SUBDIRS.values())

logger = logging.getLogger(__name__)


def _session_dirs(context_root: Path) -> list[Path]:
    return [d for d in context_root.iterdir() if d.is_dir() and d.name != "system"]


async def cleanup_context_files_async(
    retention_days: int = CONTEXT_RETENTION_DAYS,
    batch_size: int = 100,
    timeout_seconds: float = 1800.0,
    access_tracker: FileAccessTracker | None = None,
) -> int:
    """Clean up context files nothing has read or written for ``retention_days``.

    A file is kept when the access tracker recorded a read within the window, or when its
    modification time falls within it; otherwise it is removed. Without a tracker only the
    modification time counts.

    Args:
        retention_days: Window, in days, measured back from now.
        batch_size: Sessions processed per batch, so the event loop is never blocked for long.
        timeout_seconds: Maximum execution time before aborting (default: 30min).
        access_tracker: Read-access tracker. When omitted the shared tracker is used, and when
            that is unavailable cleanup falls back to modification time.

    Returns:
        Number of files removed.

    Examples:
        >>> await cleanup_context_files_async(retention_days=14)
        42

    """
    context_root = Path(get_context_root())
    if not context_root.exists():
        return 0

    if access_tracker is None:
        from .file_access_tracker import get_file_access_tracker

        try:
            access_tracker = await get_file_access_tracker()
        except Exception as exc:
            logger.warning(f"Failed to get access tracker, using fallback: {exc}")

    start_time = asyncio.get_running_loop().time()
    threshold = datetime.now(UTC) - timedelta(days=retention_days)
    removed_count = 0

    # Phase 1: Collect all session directories
    phase_start = asyncio.get_running_loop().time()
    session_dirs = _session_dirs(context_root)
    total_sessions = len(session_dirs)
    record_cleanup_phase_duration("file_scanning", asyncio.get_running_loop().time() - phase_start)

    # Process sessions in batches
    for batch_start in range(0, total_sessions, batch_size):
        elapsed = asyncio.get_running_loop().time() - start_time
        if elapsed > timeout_seconds:
            logger.warning(f"Cleanup timeout after {elapsed:.1f}s, processed {batch_start}/{total_sessions} sessions")
            break

        batch_end = min(batch_start + batch_size, total_sessions)

        # Collect all files in this batch for one tracker query
        batch_files: list[Path] = []
        for session_dir in session_dirs[batch_start:batch_end]:
            for subdir in _CLEANABLE_SUBDIRS:
                subdir_path = session_dir / subdir
                if not subdir_path.exists():
                    continue
                batch_files.extend(f for f in subdir_path.iterdir() if f.is_file())

        # Phase 2: One batch query for recorded reads
        batch_access_times: dict[str, datetime | None] = {}
        if access_tracker and batch_files:
            query_start = asyncio.get_running_loop().time()
            try:
                batch_access_times = await access_tracker.batch_check_files(
                    file_paths=[str(f) for f in batch_files],
                    access_threshold=threshold,
                )
                record_batch_query(
                    "access_check",
                    len(batch_files),
                    asyncio.get_running_loop().time() - query_start,
                )
            except Exception as exc:
                logger.warning(f"Batch access check failed: {exc}")

        # Phase 3: Remove what neither rule protects
        deletion_start = asyncio.get_running_loop().time()
        for file_path in batch_files:
            try:
                # Rule 1: Access protection (tracked)
                last_access = batch_access_times.get(str(file_path))
                if last_access and last_access >= threshold:
                    record_protection_rule_hit("access_tracked")
                    continue

                # Rule 2: Modification protection (mtime)
                if datetime.fromtimestamp(file_path.stat().st_mtime, tz=UTC) >= threshold:
                    record_protection_rule_hit("mtime_fallback")
                    continue

                file_path.unlink()
                removed_count += 1
            except (OSError, PermissionError):
                continue

        record_cleanup_phase_duration("deletion", asyncio.get_running_loop().time() - deletion_start)

        # Yield control after each batch
        if batch_end < total_sessions:
            await asyncio.sleep(0)
            logger.info(f"Cleanup progress: {batch_end}/{total_sessions} sessions processed")

    # Phase 4: Cleanup orphan access records
    if access_tracker and removed_count > 0:
        phase_start = asyncio.get_running_loop().time()
        try:
            existing_files = _collect_existing_files(session_dirs)
            await access_tracker.cleanup_orphan_records(existing_files)
        except Exception as exc:
            logger.warning(f"Failed to cleanup orphan access records: {exc}")
        finally:
            record_cleanup_phase_duration("orphan_cleanup", asyncio.get_running_loop().time() - phase_start)

    # Record overall metrics
    total_duration = asyncio.get_running_loop().time() - start_time
    try:
        record_cleanup_duration("context_cleanup", total_duration)

        if access_tracker:
            stats = await access_tracker.get_statistics()
            record_tracker_statistics(access_tracker_records=stats.get("total_files", 0))
    except Exception as exc:
        logger.debug(f"Failed to record cleanup metrics: {exc}")

    _remove_empty_directories(session_dirs)

    return removed_count


def cleanup_context_files_local(retention_days: int = CONTEXT_RETENTION_DAYS) -> int:
    """Clean up context files not modified for ``retention_days``, without consulting a tracker.

    Args:
        retention_days: Window, in days, measured back from now.

    Returns:
        Number of files removed.

    Examples:
        >>> cleanup_context_files_local(retention_days=14)
        42

    """
    context_root = Path(get_context_root())
    if not context_root.exists():
        return 0

    threshold = datetime.now(UTC) - timedelta(days=retention_days)
    removed_count = 0

    for session_dir in _session_dirs(context_root):
        for subdir in _CLEANABLE_SUBDIRS:
            subdir_path = session_dir / subdir
            if not subdir_path.exists():
                continue

            for file_path in subdir_path.iterdir():
                if not file_path.is_file():
                    continue

                try:
                    if datetime.fromtimestamp(file_path.stat().st_mtime, tz=UTC) >= threshold:
                        continue
                    file_path.unlink()
                    removed_count += 1
                except (OSError, PermissionError):
                    continue

    return removed_count


def _remove_empty_directories(session_dirs: list[Path]) -> None:
    """Remove cleanable subdirectories and session directories the pass left empty."""
    try:
        removed = 0
        for session_dir in session_dirs:
            for subdir in _CLEANABLE_SUBDIRS:
                subdir_path = session_dir / subdir
                if subdir_path.exists() and subdir_path.is_dir():
                    try:
                        if not any(subdir_path.iterdir()):
                            subdir_path.rmdir()
                            removed += 1
                    except (OSError, PermissionError):
                        continue

            if session_dir.exists() and session_dir.is_dir():
                try:
                    if not any(session_dir.iterdir()):
                        session_dir.rmdir()
                        removed += 1
                except (OSError, PermissionError):
                    continue

        if removed > 0:
            logger.info(f"Cleaned up {removed} empty directories")
    except Exception as exc:
        logger.warning(f"Failed to cleanup empty directories: {exc}")


def _collect_existing_files(session_dirs: list[Path]) -> set[str]:
    """Collect all existing context files across sessions.

    Args:
        session_dirs: List of session directories

    Returns:
        Set of absolute file paths

    """
    return {
        str(f)
        for session_dir in session_dirs
        for subdir in _CLEANABLE_SUBDIRS
        if (subdir_path := session_dir / subdir).exists()
        for f in subdir_path.iterdir()
        if f.is_file()
    }
