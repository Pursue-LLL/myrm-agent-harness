"""Multi-Version Concurrency Control (MVCC) revision engine for point-in-time snapshot reads."""

from __future__ import annotations

import threading
import time

from myrm_agent_harness.toolkits.memory.durable_revision.models import SnapshotReadView
from myrm_agent_harness.toolkits.memory.durable_revision.wal_recovery import calculate_payload_crc32


class RevisionContentionError(Exception):
    """Raised when an optimistic expected revision check fails against canonical revision."""

    def __init__(self, key: str, expected: int, actual: int) -> None:
        super().__init__(
            f"Revision validation failed for key '{key}': expected {expected}, actual canonical is {actual}"
        )
        self.key = key
        self.expected = expected
        self.actual = actual


class RevisionNotFoundError(Exception):
    """Raised when a specific requested historical revision does not exist."""

    def __init__(self, key: str, revision: int) -> None:
        super().__init__(f"Revision {revision} not found for key '{key}'")
        self.key = key
        self.revision = revision


class MVCCRevisionEngine:
    """Thread-safe MVCC point-in-time snapshot reader and monotonic revision manager."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # key -> current canonical revision integer
        self._canonical_revisions: dict[str, int] = {}
        # key -> revision -> SnapshotReadView
        self._snapshots: dict[str, dict[int, SnapshotReadView]] = {}

    def get_canonical_revision(self, key: str) -> int:
        """Return the current canonical revision number for a key, or 0 if unwritten."""
        with self._lock:
            return self._canonical_revisions.get(key, 0)

    def commit_mutation(
        self,
        key: str,
        content: str,
        tags: dict[str, str],
        expected_revision: int | None = None,
        is_tombstone: bool = False,
    ) -> tuple[int, SnapshotReadView]:
        """Atomically advance the canonical revision and register an immutable snapshot view."""
        with self._lock:
            current_rev = self._canonical_revisions.get(key, 0)
            if expected_revision is not None and expected_revision != current_rev:
                raise RevisionContentionError(key=key, expected=expected_revision, actual=current_rev)

            next_rev = current_rev + 1
            crc = calculate_payload_crc32(key, content, tags)

            snapshot = SnapshotReadView(
                key=key,
                revision=next_rev,
                content=content,
                tags=dict(tags),
                is_tombstone=is_tombstone,
                created_at=time.time(),
                checksum_crc32=crc,
            )

            if key not in self._snapshots:
                self._snapshots[key] = {}
            self._snapshots[key][next_rev] = snapshot
            self._canonical_revisions[key] = next_rev

            return next_rev, snapshot

    def snapshot_read(
        self,
        key: str,
        target_revision: int | None = None,
    ) -> SnapshotReadView | None:
        """Point-in-time snapshot read without acquiring coarse write locks."""
        with self._lock:
            history = self._snapshots.get(key)
            if not history:
                return None

            if target_revision is None:
                current_rev = self._canonical_revisions.get(key, 0)
                return history.get(current_rev)

            return history.get(target_revision)

    def rollback_to(self, key: str, target_revision: int) -> tuple[int, SnapshotReadView]:
        """Revert key state to target_revision by publishing a new forward monotonic revision."""
        with self._lock:
            history = self._snapshots.get(key)
            if not history or target_revision not in history:
                raise RevisionNotFoundError(key=key, revision=target_revision)

            target_snap = history[target_revision]
            current_rev = self._canonical_revisions.get(key, 0)
            next_rev = current_rev + 1

            new_snapshot = SnapshotReadView(
                key=key,
                revision=next_rev,
                content=target_snap.content,
                tags=dict(target_snap.tags),
                is_tombstone=target_snap.is_tombstone,
                created_at=time.time(),
                checksum_crc32=target_snap.checksum_crc32,
            )

            history[next_rev] = new_snapshot
            self._canonical_revisions[key] = next_rev
            return next_rev, new_snapshot

    def mark_tombstone(self, key: str) -> tuple[int, SnapshotReadView]:
        """Publish a tombstone revision marking key as retracted/deleted."""
        return self.commit_mutation(
            key=key,
            content="",
            tags={},
            is_tombstone=True,
        )

    def get_history(self, key: str) -> list[SnapshotReadView]:
        """Return full immutable history of revisions for a key in ascending order."""
        with self._lock:
            history = self._snapshots.get(key, {})
            return [history[r] for r in sorted(history.keys())]

    def count_total_revisions(self) -> int:
        """Return total number of retained snapshots across all keys."""
        with self._lock:
            return sum(len(h) for h in self._snapshots.values())
