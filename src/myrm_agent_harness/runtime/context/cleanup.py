"""Context file cleanup with session-aware strategy.

Implements intelligent cleanup logic that respects:
- Active sessions (keep all files)
- Tracked file access (keep recently accessed files)
- File modification time (fallback strategy)

[INPUT]
- (none)

[OUTPUT]
- cleanup_context_files_async: Clean up expired context files with session-aware strateg...
- cleanup_context_files_local: Clean up expired context files with session-aware strategy.

[POS]
Context file cleanup with session-aware strategy.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .file_access_tracker import FileAccessTracker

from .. import execution_paths
from ..checkpoint_protocol import CheckpointerProtocol
from ..execution_paths import CONTEXT_SUBDIRS
from .session_activity import load_session_activity, load_session_activity_async

_CLEANABLE_SUBDIRS = list(CONTEXT_SUBDIRS.values())

logger = logging.getLogger(__name__)


async def cleanup_context_files_async(
    max_age_days: int = 7,
    session_active_days: int = 30,
    file_access_days: int = 14,
    batch_size: int = 100,
    timeout_seconds: float = 1800.0,
    checkpointer: CheckpointerProtocol | None = None,
    access_tracker: FileAccessTracker | None = None,
) -> int:
    """Clean up expired context files with session-aware strategy (async version).

    Smart cleanup rules:
    1. If session active within session_active_days → keep all files
    2. Else if file accessed within file_access_days → keep file (checked via access tracker)
    3. Else if file modified within max_age_days → keep file (fallback)
    4. Else → remove file

    Args:
        max_age_days: Fallback max age for files (when session info unavailable)
        session_active_days: Keep files if session active within this period (default: 30)
        file_access_days: Keep files if accessed within this period (default: 14)
        batch_size: Process sessions in batches to prevent blocking (default: 100)
        timeout_seconds: Maximum execution time before aborting (default: 30min)
        checkpointer: Optional checkpointer instance for session-aware cleanup.
                      If None, falls back to file-based cleanup strategy.
        access_tracker: Optional file access tracker for accurate access time tracking.
                        If None, uses filesystem mtime as fallback.

    Returns:
        Number of files removed

    Examples:
        >>> access_tracker = await get_file_access_tracker()
        >>> await cleanup_context_files_async(
        ...     max_age_days=7,
        ...     session_active_days=30,
        ...     access_tracker=access_tracker
        ... )
        42

    """
    if not Path(execution_paths.CONTEXT_ROOT).exists():
        return 0

    # Import metrics functions once (avoid repeated imports)
    try:
        from .context_metrics import (
            record_batch_query,
            record_cleanup_active_sessions,
            record_cleanup_duration,
            record_cleanup_phase_duration,
            record_protection_rule_hit,
            record_tracker_statistics,
        )

        metrics_available = True
    except (ImportError, TypeError):
        metrics_available = False

    # Get access tracker if not provided
    if access_tracker is None:
        from .file_access_tracker import get_file_access_tracker

        try:
            access_tracker = await get_file_access_tracker()
        except Exception as exc:
            logger.warning(f"Failed to get access tracker, using fallback: {exc}")

    start_time = asyncio.get_running_loop().time()
    now = datetime.now(UTC)
    session_active_threshold = now - timedelta(days=session_active_days)
    file_access_threshold = now - timedelta(days=file_access_days)
    fallback_threshold = now - timedelta(days=max_age_days)

    removed_count = 0
    active_session_ids: set[str] = set()

    # Phase 1: Load session activity info from checkpointer (if provided)
    phase_start = asyncio.get_running_loop().time()
    try:
        active_session_ids = await load_session_activity_async(session_active_threshold, checkpointer=checkpointer)
        if active_session_ids:
            logger.info(f"Cleanup: loaded {len(active_session_ids)} active sessions")
    except Exception as exc:
        logger.warning(f"Failed to load session activity, using fallback strategy: {exc}")
    finally:
        if metrics_available:
            record_cleanup_phase_duration("session_loading", asyncio.get_running_loop().time() - phase_start)

    # Phase 2: Collect all session directories
    phase_start = asyncio.get_running_loop().time()
    session_dirs = [d for d in Path(execution_paths.CONTEXT_ROOT).iterdir() if d.is_dir() and d.name != "system"]
    total_sessions = len(session_dirs)
    if metrics_available:
        record_cleanup_phase_duration("file_scanning", asyncio.get_running_loop().time() - phase_start)

    # Process sessions in batches
    for batch_start in range(0, total_sessions, batch_size):
        # Check timeout
        elapsed = asyncio.get_running_loop().time() - start_time
        if elapsed > timeout_seconds:
            logger.warning(f"Cleanup timeout after {elapsed:.1f}s, processed {batch_start}/{total_sessions} sessions")
            break

        batch_end = min(batch_start + batch_size, total_sessions)
        batch = session_dirs[batch_start:batch_end]

        # Collect all files in this batch for batch queries
        batch_files: dict[str, list[Path]] = {}
        all_batch_file_paths: list[str] = []

        for session_dir in batch:
            session_id = session_dir.name
            session_files: list[Path] = []

            for subdir in _CLEANABLE_SUBDIRS:
                subdir_path = session_dir / subdir
                if not subdir_path.exists():
                    continue
                for file_path in subdir_path.iterdir():
                    if file_path.is_file():
                        session_files.append(file_path)
                        all_batch_file_paths.append(str(file_path))

            if session_files:
                batch_files[session_id] = session_files

        # Phase 3: Batch queries for this batch
        batch_access_times: dict[str, datetime | None] = {}

        if access_tracker and all_batch_file_paths:
            query_start = asyncio.get_running_loop().time()
            try:
                batch_access_times = await access_tracker.batch_check_files(
                    file_paths=all_batch_file_paths,
                    access_threshold=file_access_threshold,
                )

                if metrics_available:
                    record_batch_query(
                        "access_check",
                        len(all_batch_file_paths),
                        asyncio.get_running_loop().time() - query_start,
                    )
            except Exception as exc:
                logger.warning(f"Batch access check failed: {exc}")

        # Phase 4: Process files in batch using cached query results
        deletion_start = asyncio.get_running_loop().time()

        for session_id, session_files in batch_files.items():
            is_active_session = session_id in active_session_ids

            for file_path in session_files:
                try:
                    file_path_str = str(file_path)

                    # Rule 1: Session protection
                    if is_active_session:
                        if metrics_available:
                            record_protection_rule_hit("session_active")
                        continue

                    # Rule 2: Access protection (tracked)
                    if file_path_str in batch_access_times:
                        last_access = batch_access_times[file_path_str]
                        if last_access and last_access >= file_access_threshold:
                            if metrics_available:
                                record_protection_rule_hit("access_tracked")
                            continue

                    # Rule 3: Fallback protection (mtime)
                    stat = file_path.stat()
                    file_mtime = datetime.fromtimestamp(stat.st_mtime, tz=UTC)
                    if file_mtime >= fallback_threshold:
                        if metrics_available:
                            record_protection_rule_hit("mtime_fallback")
                        continue

                    # No protection - remove file
                    file_path.unlink()
                    removed_count += 1
                except (OSError, PermissionError):
                    continue

        if metrics_available:
            record_cleanup_phase_duration("deletion", asyncio.get_running_loop().time() - deletion_start)

        # Yield control after each batch
        if batch_end < total_sessions:
            await asyncio.sleep(0)
            logger.info(f"Cleanup progress: {batch_end}/{total_sessions} sessions processed")

    # Phase 5: Cleanup orphan access records
    if access_tracker and removed_count > 0:
        phase_start = asyncio.get_running_loop().time()
        try:
            existing_files = _collect_existing_files(session_dirs)
            await access_tracker.cleanup_orphan_records(existing_files)
        except Exception as exc:
            logger.warning(f"Failed to cleanup orphan access records: {exc}")
        finally:
            if metrics_available:
                record_cleanup_phase_duration("orphan_cleanup", asyncio.get_running_loop().time() - phase_start)

    # Record overall metrics
    total_duration = asyncio.get_running_loop().time() - start_time
    if metrics_available:
        try:
            record_cleanup_duration("context_cleanup", total_duration)
            record_cleanup_active_sessions(len(active_session_ids))

            if access_tracker:
                stats = await access_tracker.get_statistics()
                record_tracker_statistics(access_tracker_records=stats.get("total_files", 0))
        except Exception as exc:
            logger.debug(f"Failed to record cleanup metrics: {exc}")

    # Cleanup empty directories
    try:
        empty_dirs_removed = 0
        for session_dir in session_dirs:
            for subdir in _CLEANABLE_SUBDIRS:
                subdir_path = session_dir / subdir
                if subdir_path.exists() and subdir_path.is_dir():
                    try:
                        if not any(subdir_path.iterdir()):
                            subdir_path.rmdir()
                            empty_dirs_removed += 1
                    except (OSError, PermissionError):
                        continue

            if session_dir.exists() and session_dir.is_dir():
                try:
                    if not any(session_dir.iterdir()):
                        session_dir.rmdir()
                        empty_dirs_removed += 1
                except (OSError, PermissionError):
                    continue

        if empty_dirs_removed > 0:
            logger.info(f"Cleaned up {empty_dirs_removed} empty directories")
    except Exception as exc:
        logger.warning(f"Failed to cleanup empty directories: {exc}")

    return removed_count


def cleanup_context_files_local(
    max_age_days: int = 7,
    session_active_days: int = 30,
    file_access_days: int = 14,
    checkpointer: CheckpointerProtocol | None = None,
) -> int:
    """Clean up expired context files with session-aware strategy.

    Smart cleanup rules:
    1. If session active within session_active_days → keep all files
    2. Else if file accessed within file_access_days → keep file
    3. Else → remove file

    Args:
        max_age_days: Fallback max age for files (when session info unavailable)
        session_active_days: Keep files if session active within this period (default: 30)
        file_access_days: Keep files if accessed within this period (default: 14)
        checkpointer: Optional checkpointer instance for session-aware cleanup.
                      If None, falls back to file-based cleanup strategy.

    Returns:
        Number of files removed

    Examples:
        >>> cleanup_context_files_local(max_age_days=7, session_active_days=30, file_access_days=14)
        42

    """
    if not Path(execution_paths.CONTEXT_ROOT).exists():
        return 0

    now = datetime.now(UTC)
    session_active_threshold = now - timedelta(days=session_active_days)
    file_access_threshold = now - timedelta(days=file_access_days)
    fallback_threshold = now - timedelta(days=max_age_days)

    removed_count = 0
    active_session_ids: set[str] = set()

    # Try to load session activity info from checkpointer (if provided)
    try:
        session_activity = load_session_activity(session_active_threshold, checkpointer=checkpointer)
        active_session_ids = session_activity
    except Exception as exc:
        logger.debug(f"Failed to load session activity: {exc}")

    for session_dir in Path(execution_paths.CONTEXT_ROOT).iterdir():
        if not session_dir.is_dir() or session_dir.name == "system":
            continue

        session_id = session_dir.name
        is_active_session = session_id in active_session_ids

        for subdir in _CLEANABLE_SUBDIRS:
            subdir_path = session_dir / subdir
            if not subdir_path.exists():
                continue

            for file_path in subdir_path.iterdir():
                if not file_path.is_file():
                    continue

                try:
                    # If session is active, keep all files
                    if is_active_session:
                        continue

                    # Check file access time
                    stat = file_path.stat()
                    file_mtime = datetime.fromtimestamp(stat.st_mtime, tz=UTC)

                    # If file accessed recently, keep it
                    if file_mtime >= file_access_threshold:
                        continue

                    # If neither condition met, check fallback threshold
                    if file_mtime >= fallback_threshold:
                        continue

                    # Remove file
                    file_path.unlink()
                    removed_count += 1
                except (OSError, PermissionError):
                    continue

    return removed_count


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
