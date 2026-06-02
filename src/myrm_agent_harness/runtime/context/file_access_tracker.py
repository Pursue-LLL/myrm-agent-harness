"""File access tracking system for context files.

Tracks file access history in SQLite to support accurate lifecycle management.
Uses explicit tracking instead of filesystem atime (which is often disabled).

[INPUT]
- (none)

[OUTPUT]
- FileAccessTracker: Track context file access history in SQLite.
- set_file_access_tracker_db_path: Configure the database path for file access tracking.
- get_file_access_tracker: Get global file access tracker instance (singleton).
- reset_tracker: Reset global tracker (for testing).

[POS]
File access tracking system for context files.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path

from myrm_agent_harness.utils.db.sqlite import connect_async

from .tracker_manager import TrackerManager

logger = logging.getLogger(__name__)


class FileAccessTracker:
    """Track context file access history in SQLite.

    Features:
    - Record file creation and access timestamps
    - Query last access time for cleanup decisions
    - Cleanup orphan tracking records
    - Thread-safe with asyncio locks

    Usage:
        >>> tracker = FileAccessTracker()
        >>> await tracker.record_access("/persistent/.context/abc/file.txt")
        >>> last_access = await tracker.get_last_access("/persistent/.context/abc/file.txt")
        >>> if last_access and last_access >= threshold:
        ...     keep_file()
    """

    def __init__(self, db_path: str | None = None) -> None:
        """Initialize file access tracker.

        Args:
            db_path: Path to SQLite database (default: /persistent/.context/.file_access.db)
        """
        if db_path is None:
            db_path = "/persistent/.context/.file_access.db"

        self._db_path = db_path
        self._lock = asyncio.Lock()
        self._initialized = False
        logger.info(f"FileAccessTracker initialized: db={db_path}")

    async def _ensure_initialized(self) -> None:
        """Ensure database is initialized (lazy initialization)."""
        if self._initialized:
            return

        async with self._lock:
            if self._initialized:
                return

            db_dir = Path(self._db_path).parent
            db_dir.mkdir(parents=True, exist_ok=True)

            async with connect_async(self._db_path) as db:
                await db.execute(
                    """
                    CREATE TABLE IF NOT EXISTS file_access (
                        file_path TEXT PRIMARY KEY,
                        session_id TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        last_accessed_at TEXT NOT NULL,
                        access_count INTEGER DEFAULT 1
                    )
                    """
                )
                await db.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_session_access
                    ON file_access (session_id, last_accessed_at)
                    """
                )
                await db.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_last_accessed
                    ON file_access (last_accessed_at)
                    """
                )
                await db.commit()

            self._initialized = True
            logger.debug("FileAccessTracker database initialized")

    async def record_access(
        self,
        file_path: str,
        session_id: str | None = None,
    ) -> None:
        """Record file access event.

        Creates new record if file not tracked, updates access time if exists.

        Args:
            file_path: Absolute path to file
            session_id: Session identifier (extracted from path if not provided)
        """
        await self._ensure_initialized()

        if session_id is None:
            session_id = self._extract_session_id(file_path)

        now = datetime.now(UTC).isoformat()

        try:
            async with connect_async(self._db_path) as db:
                await db.execute(
                    """
                    INSERT INTO file_access (file_path, session_id, created_at, last_accessed_at, access_count)
                    VALUES (?, ?, ?, ?, 1)
                    ON CONFLICT(file_path) DO UPDATE SET
                        last_accessed_at = excluded.last_accessed_at,
                        access_count = access_count + 1
                    """,
                    (file_path, session_id, now, now),
                )
                await db.commit()
        except Exception as exc:
            logger.warning(f"Failed to record access for {file_path}: {exc}")

    async def get_last_access(self, file_path: str) -> datetime | None:
        """Get last access time for file.

        Args:
            file_path: Absolute path to file

        Returns:
            Last access timestamp, or None if not tracked
        """
        await self._ensure_initialized()

        try:
            async with connect_async(self._db_path) as db, db.execute(
                "SELECT last_accessed_at FROM file_access WHERE file_path = ?",
                (file_path,),
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return datetime.fromisoformat(row[0])
                return None
        except Exception as exc:
            logger.warning(f"Failed to get last access for {file_path}: {exc}")
            return None

    async def batch_check_files(
        self,
        file_paths: list[str],
        access_threshold: datetime,
    ) -> dict[str, datetime | None]:
        """Batch check access times for multiple files.

        Returns last access time for all tracked files in the input list.
        Caller is responsible for comparing against threshold.

        Args:
            file_paths: List of file paths to check
            access_threshold: Access time threshold (unused in query, provided for context)

        Returns:
            Dictionary mapping file_path to last_access_time for tracked files.
            Files not in the database are excluded from the result.

        Examples:
            >>> tracker = FileAccessTracker()
            >>> threshold = datetime.now(UTC) - timedelta(days=14)
            >>> results = await tracker.batch_check_files(file_paths, threshold)
            >>> for path, last_access in results.items():
            ...     if last_access and last_access >= threshold:
            ...         keep_file(path)
        """
        if not file_paths:
            return {}

        await self._ensure_initialized()

        try:
            async with connect_async(self._db_path) as db:
                placeholders = ",".join("?" * len(file_paths))
                query = f"""
                    SELECT file_path, last_accessed_at
                    FROM file_access
                    WHERE file_path IN ({placeholders})
                """

                async with db.execute(query, file_paths) as cursor:
                    rows = await cursor.fetchall()
                    return {row[0]: datetime.fromisoformat(row[1]) for row in rows}
        except Exception as exc:
            logger.warning(f"Batch check failed for {len(file_paths)} files: {exc}")
            return {}

    async def get_session_files(
        self,
        session_id: str,
        accessed_after: datetime | None = None,
    ) -> list[tuple[str, datetime, int]]:
        """Get files for session with access info.

        Args:
            session_id: Session identifier
            accessed_after: Optional filter for last_accessed_at

        Returns:
            List of (file_path, last_accessed_at, access_count) tuples
        """
        await self._ensure_initialized()

        try:
            async with connect_async(self._db_path) as db:
                if accessed_after:
                    query = """
                        SELECT file_path, last_accessed_at, access_count
                        FROM file_access
                        WHERE session_id = ? AND last_accessed_at >= ?
                        ORDER BY last_accessed_at DESC
                    """
                    params = (session_id, accessed_after.isoformat())
                else:
                    query = """
                        SELECT file_path, last_accessed_at, access_count
                        FROM file_access
                        WHERE session_id = ?
                        ORDER BY last_accessed_at DESC
                    """
                    params = (session_id,)

                async with db.execute(query, params) as cursor:
                    rows = await cursor.fetchall()
                    return [(row[0], datetime.fromisoformat(row[1]), row[2]) for row in rows]
        except Exception as exc:
            logger.warning(f"Failed to get session files for {session_id}: {exc}")
            return []

    async def cleanup_orphan_records(self, existing_files: set[str]) -> int:
        """Remove tracking records for files that no longer exist.

        Args:
            existing_files: Set of file paths that currently exist

        Returns:
            Number of orphan records removed
        """
        await self._ensure_initialized()

        try:
            async with connect_async(self._db_path) as db:
                async with db.execute("SELECT file_path FROM file_access") as cursor:
                    all_paths = [row[0] for row in await cursor.fetchall()]

                orphan_paths = [p for p in all_paths if p not in existing_files]

                if orphan_paths:
                    placeholders = ",".join("?" * len(orphan_paths))
                    await db.execute(
                        f"DELETE FROM file_access WHERE file_path IN ({placeholders})",
                        orphan_paths,
                    )
                    await db.commit()
                    logger.info(f"Cleaned up {len(orphan_paths)} orphan access records")
                    return len(orphan_paths)

                return 0
        except Exception as exc:
            logger.warning(f"Failed to cleanup orphan records: {exc}")
            return 0

    async def get_statistics(self) -> dict[str, int]:
        """Get access tracking statistics.

        Returns:
            Dictionary with: total_files, total_sessions, total_accesses
        """
        await self._ensure_initialized()

        try:
            async with connect_async(self._db_path) as db, db.execute(
                """
                    SELECT
                        COUNT(*) as total_files,
                        COUNT(DISTINCT session_id) as total_sessions,
                        SUM(access_count) as total_accesses
                    FROM file_access
                    """
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return {
                        "total_files": row[0] or 0,
                        "total_sessions": row[1] or 0,
                        "total_accesses": row[2] or 0,
                    }
                return {"total_files": 0, "total_sessions": 0, "total_accesses": 0}
        except Exception as exc:
            logger.warning(f"Failed to get statistics: {exc}")
            return {"total_files": 0, "total_sessions": 0, "total_accesses": 0}

    def _extract_session_id(self, file_path: str) -> str:
        """Extract session_id from file path.

        Examples:
            >>> tracker = FileAccessTracker()
            >>> tracker._extract_session_id("/persistent/.context/chat_abc/compacted/file.txt")
            'chat_abc'
        """
        parts = file_path.split("/")
        try:
            context_idx = parts.index(".context")
            if context_idx + 1 < len(parts):
                return parts[context_idx + 1]
        except (ValueError, IndexError):
            pass

        return "unknown"

    async def delete_session_records(self, session_id: str) -> int:
        """Delete all access records for a session.

        Args:
            session_id: Session identifier

        Returns:
            Number of records deleted
        """
        await self._ensure_initialized()

        try:
            async with connect_async(self._db_path) as db:
                cursor = await db.execute(
                    "DELETE FROM file_access WHERE session_id = ?",
                    (session_id,),
                )
                await db.commit()
                return cursor.rowcount
        except Exception as exc:
            logger.warning(f"Failed to delete session records for {session_id}: {exc}")
            return 0


_tracker_db_path: str = "/persistent/.context/.file_access.db"


def set_file_access_tracker_db_path(path: str) -> None:
    """Configure the database path for file access tracking."""
    global _tracker_db_path
    _tracker_db_path = path


async def _create_file_access_tracker() -> FileAccessTracker:
    """Factory function to create FileAccessTracker instance."""
    tracker = FileAccessTracker(db_path=_tracker_db_path)
    await tracker._ensure_initialized()
    return tracker


_tracker_manager: TrackerManager[FileAccessTracker] = TrackerManager(_create_file_access_tracker)


async def get_file_access_tracker() -> FileAccessTracker:
    """Get global file access tracker instance (singleton).

    Returns:
        FileAccessTracker instance
    """
    return await _tracker_manager.get_instance()


async def reset_tracker() -> None:
    """Reset global tracker (for testing)."""
    await _tracker_manager.reset()
