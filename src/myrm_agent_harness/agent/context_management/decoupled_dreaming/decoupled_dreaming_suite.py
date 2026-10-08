# [INPUT] MemoryDriveSpec, MemoryLogEntry, GoldenMemorySnapshot, DreamingConsolidationReport from .dreaming_types, DirectMemoryDriveChannel, NightlyDreamingPipeline, LockFreeSnapshotBroadcaster
# [OUTPUT] DecoupledMemoryConsolidationSuite, DecoupledMemoryConsolidationDreamingEngineAndServerlessStateSyncSuite
# [POS] Unified facade suite orchestrating detached drive I/O, dreaming consolidation, atomic persistence, and cross-sandbox broadcast

"""Unified facade suite for decoupled memory consolidation and dreaming state sync."""

from __future__ import annotations

from .direct_drive_channel import DirectMemoryDriveChannel
from .dreaming_types import (
    DreamingConsolidationReport,
    GoldenMemorySnapshot,
    MemoryDriveSpec,
    MemoryLogEntry,
    SnapshotBroadcastNotification,
)
from .nightly_dreaming_pipeline import NightlyDreamingPipeline
from .snapshot_broadcaster import LockFreeSnapshotBroadcaster


class DecoupledMemoryConsolidationSuite:
    """Unified facade orchestrating zero-boot drive mounting, dreaming consolidation, and sync."""

    @classmethod
    def record_interaction_logs(
        cls,
        drive_spec: MemoryDriveSpec,
        entries: list[MemoryLogEntry],
    ) -> int:
        """Append interaction logs directly to the external memory volume."""
        return DirectMemoryDriveChannel.append_log_entries(drive_spec, entries)

    @classmethod
    def execute_nightly_dreaming(
        cls,
        drive_spec: MemoryDriveSpec,
        stale_threshold_days: float = 30.0,
        broadcaster: LockFreeSnapshotBroadcaster | None = None,
    ) -> tuple[GoldenMemorySnapshot, DreamingConsolidationReport]:
        """Execute the full nightly dreaming consolidation lifecycle directly on the disk drive."""
        # 1. Direct drive read without container initialization
        raw_entries = DirectMemoryDriveChannel.read_log_entries(drive_spec)

        # 2. Load previous golden snapshot if existing
        existing_snapshot = DirectMemoryDriveChannel.load_latest_snapshot(drive_spec)

        # 3. Run biological dreaming consolidation algorithm
        new_snapshot, report = NightlyDreamingPipeline.run_dreaming_consolidation(
            drive_spec=drive_spec,
            raw_entries=raw_entries,
            existing_snapshot=existing_snapshot,
            stale_threshold_days=stale_threshold_days,
        )

        # 4. Atomically persist golden snapshot back to drive
        DirectMemoryDriveChannel.save_golden_snapshot(drive_spec, new_snapshot)

        # 5. Lock-free broadcast to active sandboxes if broadcaster provided
        if broadcaster is not None:
            broadcaster.broadcast_snapshot(new_snapshot)

        return (new_snapshot, report)

    @classmethod
    def load_golden_memory_view(
        cls,
        drive_spec: MemoryDriveSpec,
    ) -> GoldenMemorySnapshot | None:
        """Load the latest consolidated golden memory snapshot with zero sandbox overhead."""
        return DirectMemoryDriveChannel.load_latest_snapshot(drive_spec)

    @classmethod
    def create_broadcaster(cls) -> LockFreeSnapshotBroadcaster:
        """Factory helper creating an in-memory lock-free snapshot broadcaster."""
        return LockFreeSnapshotBroadcaster()


# Canonical alias for roadmap naming compliance
DecoupledMemoryConsolidationDreamingEngineAndServerlessStateSyncSuite = (
    DecoupledMemoryConsolidationSuite
)
