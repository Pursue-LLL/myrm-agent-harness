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

import os
import shutil
from dataclasses import replace
from pathlib import Path

from .types import (
    StateSnapshotMetadata,
    StorageCategory,
    StorageCategoryBreakdown,
    StorageGovernanceReport,
)

# Categories that are one directory of the data directory, in report order.
_DIRECTORY_CATEGORIES: tuple[tuple[StorageCategory, str], ...] = (
    (StorageCategory.WORKSPACES, "harness"),
    (StorageCategory.VECTOR_STORE, "qdrant"),
    (StorageCategory.MEMORY_ARCHIVE, "memory"),
    (StorageCategory.EVENT_LOGS, "event_logs"),
    (StorageCategory.SNAPSHOTS, "snapshots"),
)


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


def _database_footprint(db_file: Path) -> tuple[int, int]:
    """Total bytes and file count of a SQLite database and its write-ahead log."""
    total_bytes = 0
    file_count = 0
    for path in (db_file, db_file.with_name(f"{db_file.name}-wal")):
        try:
            total_bytes += path.stat().st_size
        except OSError:
            continue
        file_count += 1
    return total_bytes, file_count


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

        sqlite_bytes, sqlite_count = _database_footprint(data_dir / "data.db")
        categories = [
            StorageCategoryBreakdown(
                category=StorageCategory.SQLITE_DATABASE,
                bytes=sqlite_bytes,
                item_count=sqlite_count,
            ),
            self._checkpoints_breakdown(),
        ]
        for category, dirname in _DIRECTORY_CATEGORIES:
            dir_bytes, file_count = _safe_dir_size_and_count(data_dir / dirname)
            categories.append(
                StorageCategoryBreakdown(
                    category=category,
                    bytes=dir_bytes,
                    item_count=file_count,
                )
            )

        total_storage = sum(cat.bytes for cat in categories)
        categories = [
            replace(cat, percentage=round((cat.bytes / total_storage) * 100, 1) if total_storage > 0 else 0.0)
            for cat in categories
        ]

        return StorageGovernanceReport(
            total_storage_bytes=total_storage,
            disk_total_bytes=disk_total,
            disk_free_bytes=disk_free,
            disk_used_percentage=disk_used_pct,
            categories=categories,
            snapshots=snapshots or [],
        )

    def _checkpoints_breakdown(self) -> StorageCategoryBreakdown:
        """Space of the checkpoint database and its write-ahead log; file sizes only, row counts would scan it."""
        checkpoint_bytes, file_count = (
            _database_footprint(self._checkpoints_db) if self._checkpoints_db is not None else (0, 0)
        )
        return StorageCategoryBreakdown(
            category=StorageCategory.CHECKPOINTS,
            bytes=checkpoint_bytes,
            item_count=file_count,
        )
