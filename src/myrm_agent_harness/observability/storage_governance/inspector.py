"""Storage inspector for Agent persistent state storage governance.

[INPUT]
- Path (POS: root data directory)
- Mapping[StorageCategory, Iterable[Path]] (POS: where the application keeps each category, which it alone knows)

[OUTPUT]
- StorageGovernanceInspector.inspect() -> StorageGovernanceReport

[POS]
Core inspection and space attribution analyzer for storage governance: it measures what the application declares
and reports every other byte of the data directory as `OTHER`, so the categories add up to the whole.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterable, Mapping
from pathlib import Path

from .layout import resolve_layout
from .types import (
    StateSnapshotMetadata,
    StorageCategory,
    StorageCategoryBreakdown,
    StorageGovernanceReport,
)
from .walker import TreeSize, measure_tree


def _disk_usage(path: Path) -> tuple[int, int, float]:
    """Total bytes, free bytes and used percentage of the disk holding `path`; zeros when it cannot be read."""
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        usage = shutil.disk_usage(probe)
    except OSError:
        return 0, 0, 0.0
    used_percentage = round((usage.used / usage.total) * 100, 2) if usage.total > 0 else 0.0
    return usage.total, usage.free, used_percentage


def _measure_category(paths: Iterable[Path], owned: frozenset[str]) -> TreeSize:
    """Size of everything one category owns."""
    measured = [measure_tree(str(path), owned) for path in paths]
    return TreeSize(sum(size.total_bytes for size in measured), sum(size.file_count for size in measured))


class StorageGovernanceInspector:
    """Inspects and attributes disk space across agent persistent storage domains."""

    def __init__(
        self,
        data_dir: Path | str,
        *,
        layout: Mapping[StorageCategory, Iterable[Path | str]],
    ) -> None:
        """`layout` maps each category to the paths the application keeps it in, wherever those are.

        Nested paths are fine: a file counts toward the category with the deepest path above it. Everything in
        `data_dir` that no path claims is reported as `StorageCategory.OTHER`, which cannot be declared.
        """
        self._layout = resolve_layout(data_dir, layout)

    def inspect(self, snapshots: list[StateSnapshotMetadata] | None = None) -> StorageGovernanceReport:
        """Generate a full storage governance report; nothing on disk is created or modified."""
        layout = self._layout
        disk_total, disk_free, disk_used_percentage = _disk_usage(layout.data_dir)

        sizes = {category: _measure_category(paths, layout.owned) for category, paths in layout.claims.items()}
        total_storage = sum(size.total_bytes for size in sizes.values())
        categories = [
            StorageCategoryBreakdown(
                category=category,
                bytes=size.total_bytes,
                item_count=size.file_count,
                percentage=round((size.total_bytes / total_storage) * 100, 1) if total_storage > 0 else 0.0,
            )
            for category, size in sizes.items()
        ]

        return StorageGovernanceReport(
            total_storage_bytes=total_storage,
            disk_total_bytes=disk_total,
            disk_free_bytes=disk_free,
            disk_used_percentage=disk_used_percentage,
            categories=categories,
            snapshots=snapshots or [],
        )
