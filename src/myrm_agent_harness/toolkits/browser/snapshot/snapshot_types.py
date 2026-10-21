"""Snapshot data types and enums.

[INPUT]
- (none)

[OUTPUT]
- SnapshotSource: - FULL: Force full snapshot (first capture or after navig...
- SnapshotMetrics: SnapshotStatisticsMetrics
- AriaSnapshot: immutable ARIA Snapshot

[POS]
Snapshot data types and enums.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .aria_types import RefInfo


class SnapshotSource(StrEnum):
    """Snapshot source type.

    - FULL: Force full snapshot (first capture or after navigation)
    - FULL_WITH_CHANGES: Full re-capture after MutationObserver detected changes
    - CACHED: No changes detected, using cached snapshot
    """

    FULL = "full"
    FULL_WITH_CHANGES = "full_with_changes"
    CACHED = "cached"


@dataclass(frozen=True)
class SnapshotMetrics:
    """Snapshot statistics metrics."""

    ref_count: int
    estimated_tokens: int
    changed_regions: int
    total_changes: int


@dataclass(frozen=True)
class AriaSnapshot:
    """Immutable ARIA snapshot.

    Contains the ARIA tree, element references, and metadata. frozen=True guarantees immutability.

    Data layers:
    - Core data: tree, refs
    - Metadata: source, timestamp
    - Statistics: metrics (optional)
    """

    tree: str
    refs: dict[str, RefInfo]
    source: str
    timestamp: float
    metrics: SnapshotMetrics | None = None

    @classmethod
    def create_empty(cls, source: str = SnapshotSource.FULL) -> AriaSnapshot:
        """Create an empty snapshot."""
        return cls(
            tree="",
            refs={},
            source=source,
            timestamp=time.time(),
            metrics=None,
        )

    @classmethod
    def create_error(cls, message: str) -> AriaSnapshot:
        """Create an error snapshot."""
        return cls(
            tree=message,
            refs={},
            source=SnapshotSource.FULL,
            timestamp=time.time(),
            metrics=None,
        )

    @classmethod
    def create_cross_origin(cls) -> AriaSnapshot:
        """Create a cross-origin iframe snapshot."""
        return cls(
            tree="[Cross-origin iframe - content not accessible]",
            refs={},
            source=SnapshotSource.FULL,
            timestamp=time.time(),
            metrics=None,
        )
