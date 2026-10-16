"""Compaction of the state database for Agent persistent state storage governance.

[INPUT]
- Path (POS: root data directory)

[OUTPUT]
- StateStorageCompactor.compact() -> CompactionResult

[POS]
Truncates the state database's write-ahead log and reclaims its free pages without locking readers or writers out.
Checkpoint history is not compacted here: `runtime/checkpointing/pruning.py` prunes and shrinks its own database.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path

from .types import CompactionResult

logger = logging.getLogger(__name__)

_DATABASE_FILE = "data.db"
_BUSY_TIMEOUT_SECONDS = 5.0
_AUTO_VACUUM_INCREMENTAL = 2


def _footprint_bytes(db_file: Path) -> int:
    """Bytes the database file and its write-ahead log occupy on disk."""
    total = 0
    for path in (db_file, db_file.with_name(f"{db_file.name}-wal")):
        try:
            total += path.stat().st_size
        except OSError:
            continue
    return total


def _compact_database(db_file: Path, incremental_pages: int) -> bool:
    """Truncate the write-ahead log and reclaim free pages; True when no reader kept the log from being emptied."""
    conn = sqlite3.connect(str(db_file), timeout=_BUSY_TIMEOUT_SECONDS)
    try:
        busy: int = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0]
        auto_vacuum: int = conn.execute("PRAGMA auto_vacuum").fetchone()[0]
        if auto_vacuum == _AUTO_VACUUM_INCREMENTAL:
            # The pragma frees one page per fetched row, so it only reclaims what is read to the end.
            conn.execute(f"PRAGMA incremental_vacuum({incremental_pages})").fetchall()
        else:
            conn.execute("PRAGMA optimize")
        conn.commit()
        return busy == 0
    finally:
        conn.close()


class StateStorageCompactor:
    """Compacts the state database (`data.db`) of a data directory."""

    def __init__(self, data_dir: Path | str) -> None:
        self._data_dir = Path(data_dir)

    def compact(self, incremental_pages: int = 500) -> CompactionResult:
        """Truncate the write-ahead log and reclaim up to `incremental_pages` free pages of the state database."""
        started = time.perf_counter()
        db_file = self._data_dir / _DATABASE_FILE
        if not db_file.exists():
            return CompactionResult(
                success=True,
                initial_bytes=0,
                final_bytes=0,
                freed_bytes=0,
                message="No state database to compact.",
            )

        initial_bytes = _footprint_bytes(db_file)
        try:
            wal_truncated = _compact_database(db_file, max(0, int(incremental_pages)))
        except sqlite3.Error:
            logger.warning("State database compaction failed for %s", db_file, exc_info=True)
            return CompactionResult(
                success=False,
                initial_bytes=initial_bytes,
                final_bytes=_footprint_bytes(db_file),
                freed_bytes=0,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
                message="State database compaction did not complete.",
            )

        final_bytes = _footprint_bytes(db_file)
        freed_bytes = max(0, initial_bytes - final_bytes)
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        return CompactionResult(
            success=True,
            initial_bytes=initial_bytes,
            final_bytes=final_bytes,
            freed_bytes=freed_bytes,
            wal_truncated=wal_truncated,
            duration_ms=elapsed_ms,
            message=f"Compaction finished in {elapsed_ms}ms. Freed {freed_bytes} bytes.",
        )
