"""Storage inspector for Agent persistent state storage governance.

[INPUT]
- Path (POS: root data directory)

[OUTPUT]
- StorageGovernanceInspector.inspect() -> StorageGovernanceReport

[POS]
Core inspection and space attribution analyzer for storage governance.
"""

from __future__ import annotations

import logging
import os
import shutil
import sqlite3
from pathlib import Path

from .types import (
    StateSnapshotMetadata,
    StorageCategory,
    StorageCategoryBreakdown,
    StorageGovernanceReport,
)

logger = logging.getLogger(__name__)


def _safe_dir_size_and_count(dir_path: Path) -> tuple[int, int]:
    """Calculate directory size in bytes and file count safely without raising exceptions."""
    if not dir_path.exists():
        return 0, 0
    total_bytes = 0
    file_count = 0
    try:
        for root, _, files in os.walk(dir_path):
            for file in files:
                file_path = Path(root) / file
                try:
                    total_bytes += file_path.stat().st_size
                    file_count += 1
                except OSError:
                    continue
    except OSError:
        pass
    return total_bytes, file_count


def _get_sqlite_table_stats(db_path: Path) -> dict[str, int]:
    """Attempt to retrieve per-table approximate row counts or page allocations."""
    if not db_path.exists():
        return {}
    details: dict[str, int] = {}
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2.0)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = [row[0] for row in cursor.fetchall() if not row[0].startswith("sqlite_")]
            for table in tables:
                try:
                    cursor.execute(f"SELECT COUNT(*) FROM \"{table}\";")
                    count_row = cursor.fetchone()
                    if count_row:
                        details[table] = count_row[0]
                except sqlite3.Error:
                    continue
        finally:
            conn.close()
    except Exception as exc:
        logger.debug("Failed to inspect SQLite table stats for %s: %s", db_path, exc)
    return details


class StorageGovernanceInspector:
    """Inspects and attributes disk space across agent persistent storage domains."""

    def __init__(self, data_dir: Path | str) -> None:
        self._data_dir = Path(data_dir)

    def inspect(self, snapshots: list[StateSnapshotMetadata] | None = None) -> StorageGovernanceReport:
        """Generate a full storage governance report for the target data directory."""
        data_dir = self._data_dir
        if not data_dir.exists():
            data_dir.mkdir(parents=True, exist_ok=True)

        try:
            disk = shutil.disk_usage(data_dir)
            disk_total = disk.total
            disk_free = disk.free
            disk_used = disk.used
            disk_used_pct = round((disk_used / disk_total) * 100, 2) if disk_total > 0 else 0.0
        except OSError:
            disk_total = 0
            disk_free = 0
            disk_used_pct = 0.0

        categories: list[StorageCategoryBreakdown] = []

        # 1. SQLite Database (data.db, wal, shm)
        sqlite_bytes = 0
        sqlite_count = 0
        sqlite_details: dict[str, int] = {}
        db_file = data_dir / "data.db"
        if db_file.exists():
            try:
                db_size = db_file.stat().st_size
                sqlite_bytes += db_size
                sqlite_count += 1
                sqlite_details["data.db"] = db_size
                sqlite_details.update(_get_sqlite_table_stats(db_file))
            except OSError:
                pass
        wal_file = data_dir / "data.db-wal"
        if wal_file.exists():
            try:
                wal_size = wal_file.stat().st_size
                sqlite_bytes += wal_size
                sqlite_count += 1
                sqlite_details["data.db-wal"] = wal_size
            except OSError:
                pass

        categories.append(
            StorageCategoryBreakdown(
                category=StorageCategory.SQLITE_DATABASE,
                display_name="SQLite State Database",
                bytes=sqlite_bytes,
                item_count=sqlite_count,
                details=sqlite_details,
            )
        )

        # 2. Checkpoints & Runtime state
        cp_dir = data_dir / "harness"
        cp_bytes, cp_count = _safe_dir_size_and_count(cp_dir)
        categories.append(
            StorageCategoryBreakdown(
                category=StorageCategory.CHECKPOINTS,
                display_name="Session Checkpoints",
                bytes=cp_bytes,
                item_count=cp_count,
            )
        )

        # 3. Qdrant Vector Store
        qdrant_dir = data_dir / "qdrant"
        qdrant_bytes, qdrant_count = _safe_dir_size_and_count(qdrant_dir)
        categories.append(
            StorageCategoryBreakdown(
                category=StorageCategory.VECTOR_STORE,
                display_name="Vector Index & Embeddings",
                bytes=qdrant_bytes,
                item_count=qdrant_count,
            )
        )

        # 4. Long-term Memory Archive
        mem_dir = data_dir / "memory"
        mem_bytes, mem_count = _safe_dir_size_and_count(mem_dir)
        categories.append(
            StorageCategoryBreakdown(
                category=StorageCategory.MEMORY_ARCHIVE,
                display_name="Long-Term Memory Archive",
                bytes=mem_bytes,
                item_count=mem_count,
            )
        )

        # 5. Event Logs & Traces
        logs_dir = data_dir / "event_logs"
        logs_bytes, logs_count = _safe_dir_size_and_count(logs_dir)
        categories.append(
            StorageCategoryBreakdown(
                category=StorageCategory.EVENT_LOGS,
                display_name="Event Logs & Traces",
                bytes=logs_bytes,
                item_count=logs_count,
            )
        )

        # 6. Snapshots
        snap_dir = data_dir / "snapshots"
        snap_bytes, snap_count = _safe_dir_size_and_count(snap_dir)
        categories.append(
            StorageCategoryBreakdown(
                category=StorageCategory.SNAPSHOTS,
                display_name="State Snapshots",
                bytes=snap_bytes,
                item_count=snap_count,
            )
        )

        total_storage = sum(cat.bytes for cat in categories)

        # Compute percentage for each category
        updated_categories: list[StorageCategoryBreakdown] = []
        for cat in categories:
            pct = round((cat.bytes / total_storage) * 100, 1) if total_storage > 0 else 0.0
            updated_categories.append(
                StorageCategoryBreakdown(
                    category=cat.category,
                    display_name=cat.display_name,
                    bytes=cat.bytes,
                    item_count=cat.item_count,
                    percentage=pct,
                    details=cat.details,
                )
            )

        # Formulate proactive recommendations
        recommended_actions: list[str] = []
        wal_size = sqlite_details.get("data.db-wal", 0)
        if wal_size > 50 * 1024 * 1024:  # > 50 MB WAL
            recommended_actions.append("WAL log is over 50MB. Run safe compaction to truncate and flush pages.")
        if cp_bytes > 500 * 1024 * 1024:  # > 500 MB checkpoints
            recommended_actions.append("Checkpoint storage exceeds 500MB. Prune completed task checkpoints.")
        if logs_bytes > 300 * 1024 * 1024:  # > 300 MB logs
            recommended_actions.append("Event logs exceed 300MB. Archive historical trace logs.")
        if not snapshots and total_storage > 100 * 1024 * 1024:
            recommended_actions.append("No state snapshot found. Create a baseline snapshot before agent tuning.")

        is_healthy = disk_used_pct < 85.0 and total_storage < 2 * 1024 * 1024 * 1024  # < 2GB

        return StorageGovernanceReport(
            total_storage_bytes=total_storage,
            disk_total_bytes=disk_total,
            disk_free_bytes=disk_free,
            disk_used_percentage=disk_used_pct,
            categories=updated_categories,
            snapshots=snapshots or [],
            recommended_actions=recommended_actions,
            is_growth_healthy=is_healthy,
        )
