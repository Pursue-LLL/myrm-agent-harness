"""Storage inspector for Agent persistent state storage governance.

[INPUT]
- Path (POS: root data directory)
- Path | None (POS: checkpoint database, whose location the application chooses)

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
from dataclasses import replace
from pathlib import Path

from .types import (
    StateSnapshotMetadata,
    StorageCategory,
    StorageCategoryBreakdown,
    StorageGovernanceReport,
)

logger = logging.getLogger(__name__)

# Categories that are one directory of the data directory, in report order.
_DIRECTORY_CATEGORIES: tuple[tuple[StorageCategory, str, str], ...] = (
    (StorageCategory.WORKSPACES, "harness", "Agent Workspaces"),
    (StorageCategory.VECTOR_STORE, "qdrant", "Vector Index & Embeddings"),
    (StorageCategory.MEMORY_ARCHIVE, "memory", "Long-Term Memory Archive"),
    (StorageCategory.EVENT_LOGS, "event_logs", "Event Logs & Traces"),
    (StorageCategory.SNAPSHOTS, "snapshots", "State Snapshots"),
)

_WAL_WARNING_BYTES = 50 * 1024 * 1024
_EVENT_LOGS_WARNING_BYTES = 300 * 1024 * 1024
_SNAPSHOT_ADVICE_MIN_STORAGE_BYTES = 100 * 1024 * 1024
_HEALTHY_MAX_STORAGE_BYTES = 2 * 1024 * 1024 * 1024
_HEALTHY_MAX_DISK_USED_PERCENT = 85.0


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


def _database_footprint(db_file: Path) -> tuple[int, int, dict[str, int]]:
    """Total bytes, file count and per-file sizes of a SQLite database and its write-ahead log."""
    total_bytes = 0
    sizes: dict[str, int] = {}
    for path in (db_file, db_file.with_name(f"{db_file.name}-wal")):
        try:
            sizes[path.name] = path.stat().st_size
        except OSError:
            continue
        total_bytes += sizes[path.name]
    return total_bytes, len(sizes), sizes


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
                    cursor.execute(f'SELECT COUNT(*) FROM "{table}";')
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

    def __init__(self, data_dir: Path | str, *, checkpoints_db: Path | str | None = None) -> None:
        """`checkpoints_db` is the checkpoint database file; without it no space is attributed to checkpoints."""
        self._data_dir = Path(data_dir)
        self._checkpoints_db = Path(checkpoints_db) if checkpoints_db is not None else None

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

        sqlite_bytes, sqlite_count, sqlite_details = _database_footprint(data_dir / "data.db")
        if "data.db" in sqlite_details:
            sqlite_details.update(_get_sqlite_table_stats(data_dir / "data.db"))
        categories = [
            StorageCategoryBreakdown(
                category=StorageCategory.SQLITE_DATABASE,
                display_name="SQLite State Database",
                bytes=sqlite_bytes,
                item_count=sqlite_count,
                details=sqlite_details,
            ),
            self._checkpoints_breakdown(),
        ]
        for category, dirname, display_name in _DIRECTORY_CATEGORIES:
            dir_bytes, file_count = _safe_dir_size_and_count(data_dir / dirname)
            categories.append(
                StorageCategoryBreakdown(
                    category=category,
                    display_name=display_name,
                    bytes=dir_bytes,
                    item_count=file_count,
                )
            )

        total_storage = sum(cat.bytes for cat in categories)
        categories = [
            replace(cat, percentage=round((cat.bytes / total_storage) * 100, 1) if total_storage > 0 else 0.0)
            for cat in categories
        ]

        bytes_by_category = {cat.category: cat.bytes for cat in categories}
        recommended_actions: list[str] = []
        if sqlite_details.get("data.db-wal", 0) > _WAL_WARNING_BYTES:
            recommended_actions.append("WAL log is over 50MB. Run safe compaction to truncate and flush pages.")
        if bytes_by_category[StorageCategory.EVENT_LOGS] > _EVENT_LOGS_WARNING_BYTES:
            recommended_actions.append("Event logs exceed 300MB. Archive historical trace logs.")
        if not snapshots and total_storage > _SNAPSHOT_ADVICE_MIN_STORAGE_BYTES:
            recommended_actions.append("No state snapshot found. Create a baseline snapshot before agent tuning.")

        is_healthy = disk_used_pct < _HEALTHY_MAX_DISK_USED_PERCENT and total_storage < _HEALTHY_MAX_STORAGE_BYTES

        return StorageGovernanceReport(
            total_storage_bytes=total_storage,
            disk_total_bytes=disk_total,
            disk_free_bytes=disk_free,
            disk_used_percentage=disk_used_pct,
            categories=categories,
            snapshots=snapshots or [],
            recommended_actions=recommended_actions,
            is_growth_healthy=is_healthy,
        )

    def _checkpoints_breakdown(self) -> StorageCategoryBreakdown:
        """Space of the checkpoint database and its write-ahead log; file sizes only, row counts would scan it."""
        checkpoint_bytes, file_count, sizes = (
            _database_footprint(self._checkpoints_db) if self._checkpoints_db is not None else (0, 0, {})
        )
        return StorageCategoryBreakdown(
            category=StorageCategory.CHECKPOINTS,
            display_name="Conversation Checkpoints",
            bytes=checkpoint_bytes,
            item_count=file_count,
            details=sizes,
        )
