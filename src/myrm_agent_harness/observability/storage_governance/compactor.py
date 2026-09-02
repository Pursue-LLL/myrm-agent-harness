"""Compaction engine for Agent persistent state storage governance.

[INPUT]
- Path (POS: root data directory)

[OUTPUT]
- StateStorageCompactor.compact() -> CompactionResult

[POS]
Execution primitives for non-blocking incremental vacuum, WAL truncation, and checkpoint cleanup.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import time
from pathlib import Path

from .types import CompactionResult

logger = logging.getLogger(__name__)


def _measure_dir_size(data_dir: Path) -> int:
    """Safely calculate total bytes under data directory."""
    if not data_dir.exists():
        return 0
    total = 0
    for root, _, files in os.walk(data_dir):
        for f in files:
            try:
                total += (Path(root) / f).stat().st_size
            except OSError:
                continue
    return total


class StateStorageCompactor:
    """Executes safe, non-blocking storage compaction operations."""

    def __init__(self, data_dir: Path | str) -> None:
        self._data_dir = Path(data_dir)

    def compact(
        self,
        purge_orphan_checkpoints: bool = True,
        incremental_pages: int = 500,
        max_orphan_age_seconds: float = 86400 * 7,  # 7 days
    ) -> CompactionResult:
        """Execute safe compaction across SQLite database and checkpoint folders."""
        start_time = time.perf_counter()
        data_dir = self._data_dir
        if not data_dir.exists():
            return CompactionResult(
                success=True,
                initial_bytes=0,
                final_bytes=0,
                freed_bytes=0,
                message="Data directory does not exist; nothing to compact.",
            )

        initial_bytes = _measure_dir_size(data_dir)
        wal_truncated = False
        purged_count = 0

        # 1. SQLite WAL truncation & Incremental Vacuum
        db_file = data_dir / "data.db"
        if db_file.exists():
            try:
                conn = sqlite3.connect(str(db_file), timeout=5.0)
                try:
                    # Truncate WAL
                    conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
                    wal_truncated = True

                    # Run incremental vacuum if enabled
                    cursor = conn.cursor()
                    cursor.execute("PRAGMA auto_vacuum;")
                    auto_vac_mode = cursor.fetchone()
                    if auto_vac_mode and auto_vac_mode[0] == 2:  # 2 = INCREMENTAL
                        conn.execute(f"PRAGMA incremental_vacuum({incremental_pages});")
                    else:
                        conn.execute("PRAGMA optimize;")
                    conn.commit()
                finally:
                    conn.close()
            except Exception as exc:
                logger.warning("SQLite compaction warning for %s: %s", db_file, exc)

        # 2. Checkpoints / temporary files cleanup
        if purge_orphan_checkpoints:
            cp_dir = data_dir / "harness"
            if cp_dir.exists():
                now = time.time()
                for root, _, files in os.walk(cp_dir):
                    for f in files:
                        file_path = Path(root) / f
                        if f.endswith(".tmp") or f.startswith("orphan_"):
                            try:
                                if (
                                    now - file_path.stat().st_mtime
                                    > max_orphan_age_seconds
                                ):
                                    file_path.unlink(missing_ok=True)
                                    purged_count += 1
                            except OSError:
                                continue

        final_bytes = _measure_dir_size(data_dir)
        freed_bytes = max(0, initial_bytes - final_bytes)
        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)

        return CompactionResult(
            success=True,
            initial_bytes=initial_bytes,
            final_bytes=final_bytes,
            freed_bytes=freed_bytes,
            purged_checkpoints=purged_count,
            wal_truncated=wal_truncated,
            duration_ms=elapsed_ms,
            message=f"Compaction finished in {elapsed_ms}ms. Freed {freed_bytes} bytes.",
        )
