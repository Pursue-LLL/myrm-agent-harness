# [INPUT] GoldenMemorySnapshot, SnapshotBroadcastNotification from .dreaming_types
# [OUTPUT] LockFreeSnapshotBroadcaster
# [POS] Lock-free snapshot broadcaster notifying concurrent agent sandboxes of newly consolidated golden snapshots

"""Lock-free memory snapshot broadcaster for cross-sandbox synchronization."""

from __future__ import annotations

import time
import uuid

from .dreaming_types import (
    GoldenMemorySnapshot,
    SnapshotBroadcastNotification,
)


class LockFreeSnapshotBroadcaster:
    """Dispatches notification events to active sandboxes allowing zero-copy reload."""

    def __init__(self) -> None:
        self._active_sandboxes: set[str] = set()
        self._latest_snapshots: dict[str, GoldenMemorySnapshot] = {}
        self._pending_notifications: dict[str, list[SnapshotBroadcastNotification]] = {}
        self._acknowledgements: dict[str, set[str]] = {}  # snapshot_id -> set of sandbox_ids

    def register_sandbox(self, sandbox_id: str) -> None:
        """Register an active agent sandbox to receive dreaming updates."""
        self._active_sandboxes.add(sandbox_id)
        if sandbox_id not in self._pending_notifications:
            self._pending_notifications[sandbox_id] = []

    def unregister_sandbox(self, sandbox_id: str) -> None:
        """Deregister a terminating sandbox."""
        self._active_sandboxes.discard(sandbox_id)
        self._pending_notifications.pop(sandbox_id, None)

    def get_active_sandboxes(self) -> list[str]:
        """Return list of all registered sandbox identifiers."""
        return sorted(list(self._active_sandboxes))

    def broadcast_snapshot(
        self,
        snapshot: GoldenMemorySnapshot,
        target_sandbox_ids: list[str] | None = None,
    ) -> SnapshotBroadcastNotification:
        """Broadcast a newly synthesized golden snapshot to target or all registered sandboxes."""
        targets = (
            target_sandbox_ids
            if target_sandbox_ids is not None
            else list(self._active_sandboxes)
        )
        self._latest_snapshots[snapshot.drive_id] = snapshot

        notification = SnapshotBroadcastNotification(
            broadcast_id=f"bcast_{uuid.uuid4().hex[:12]}",
            snapshot_id=snapshot.snapshot_id,
            version=snapshot.version,
            drive_id=snapshot.drive_id,
            checksum_sha256=snapshot.checksum_sha256,
            timestamp_unix=time.time(),
            target_sandbox_ids=sorted(targets),
            ack_count=0,
        )

        for sbox in targets:
            if sbox in self._pending_notifications:
                self._pending_notifications[sbox].append(notification)

        if snapshot.snapshot_id not in self._acknowledgements:
            self._acknowledgements[snapshot.snapshot_id] = set()

        return notification

    def acknowledge_notification(self, sandbox_id: str, snapshot_id: str) -> bool:
        """Record a client sandbox's acknowledgement that it has refreshed to this snapshot."""
        if snapshot_id not in self._acknowledgements:
            return False
        self._acknowledgements[snapshot_id].add(sandbox_id)

        # Clear from pending
        if sandbox_id in self._pending_notifications:
            self._pending_notifications[sandbox_id] = [
                n
                for n in self._pending_notifications[sandbox_id]
                if n.snapshot_id != snapshot_id
            ]
        return True

    def get_pending_notifications(
        self, sandbox_id: str
    ) -> list[SnapshotBroadcastNotification]:
        """Retrieve queued snapshot notifications for a given sandbox."""
        return list(self._pending_notifications.get(sandbox_id, []))

    def get_latest_snapshot(self, drive_id: str) -> GoldenMemorySnapshot | None:
        """Retrieve the latest registered golden snapshot for a drive."""
        return self._latest_snapshots.get(drive_id)
