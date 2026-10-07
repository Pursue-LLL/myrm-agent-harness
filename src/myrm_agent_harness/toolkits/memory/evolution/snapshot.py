"""Lineage snapshot and rollback engine for evolving memory rules.

[INPUT]
- toolkits.memory.evolution.models::EvolvingMemoryRule, MemorySnapshot (POS: Data models for Order-Invariant
  Memory Evolution and Decay Engine.)

[OUTPUT]
- MemoryLineageSnapshotEngine: Provides point-in-time snapshotting, cryptographic checksumming, and atomic
  rollback.

[POS]
Lineage snapshot and rollback engine for evolving memory rules.
"""

import hashlib
import json
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from .models import EvolvingMemoryRule, MemorySnapshot


class MemoryLineageSnapshotEngine:
    """Provides point-in-time snapshotting, cryptographic checksumming, and atomic rollback."""

    def __init__(self) -> None:
        """Initialize in-memory snapshot lineage history."""
        self._snapshots: dict[str, MemorySnapshot] = {}
        self._latest_snapshot_id: str | None = None

    @property
    def latest_snapshot_id(self) -> str | None:
        """Return identifier of the most recent snapshot."""
        return self._latest_snapshot_id

    def create_snapshot(
        self,
        rules: Sequence[EvolvingMemoryRule],
        commit_message: str,
        timestamp: datetime | None = None,
    ) -> MemorySnapshot:
        """Create and register a new immutable lineage snapshot.

        Args:
            rules: Current set of memory rules.
            commit_message: User or automated message explaining the evolution commit.
            timestamp: Optional specific timestamp.

        Returns:
            The registered MemorySnapshot.
        """
        now = timestamp or datetime.now(UTC)
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)

        snapshot_id = f"snap-{uuid.uuid4().hex[:12]}"
        checksum = self._compute_checksum(rules)

        # Deep-copy rules via model reconstruction
        cloned_rules = [r.model_copy(deep=True) for r in rules]

        snapshot = MemorySnapshot(
            snapshot_id=snapshot_id,
            parent_snapshot_id=self._latest_snapshot_id,
            commit_message=commit_message,
            created_at=now,
            rules=cloned_rules,
            rule_checksum=checksum,
        )

        self._snapshots[snapshot_id] = snapshot
        self._latest_snapshot_id = snapshot_id
        return snapshot

    def get_snapshot(self, snapshot_id: str) -> MemorySnapshot | None:
        """Retrieve snapshot by ID."""
        return self._snapshots.get(snapshot_id)

    def list_snapshots(self) -> list[MemorySnapshot]:
        """Return all historical snapshots ordered by creation time."""
        return sorted(self._snapshots.values(), key=lambda s: s.created_at)

    def rollback(
        self,
        target_snapshot_id: str,
        rollback_message: str | None = None,
        timestamp: datetime | None = None,
    ) -> tuple[list[EvolvingMemoryRule], MemorySnapshot]:
        """Roll back to target snapshot state and record a new rollback commit in lineage.

        Args:
            target_snapshot_id: ID of snapshot to restore.
            rollback_message: Optional custom commit message for the rollback action.
            timestamp: Optional rollback timestamp.

        Returns:
            Tuple of (restored_rules, new_rollback_snapshot).

        Raises:
            KeyError: If target_snapshot_id does not exist.
        """
        target = self.get_snapshot(target_snapshot_id)
        if target is None:
            raise KeyError(f"Snapshot with ID '{target_snapshot_id}' does not exist.")

        msg = rollback_message or f"Rollback to snapshot {target_snapshot_id}: {target.commit_message}"
        # Create a new snapshot reflecting the restored state to maintain immutable audit lineage
        new_snapshot = self.create_snapshot(
            rules=target.rules,
            commit_message=msg,
            timestamp=timestamp,
        )

        # Return detached deep-copies of restored rules
        restored = [r.model_copy(deep=True) for r in new_snapshot.rules]
        return restored, new_snapshot

    def verify_integrity(self, snapshot_id: str) -> bool:
        """Verify cryptographic checksum integrity of stored snapshot."""
        target = self.get_snapshot(snapshot_id)
        if target is None:
            return False
        expected = self._compute_checksum(target.rules)
        return expected == target.rule_checksum

    def _compute_checksum(self, rules: Sequence[EvolvingMemoryRule]) -> str:
        """Generate deterministic SHA-256 digest over normalized rule states."""
        canonical_items: list[dict[str, str | float]] = []
        for r in sorted(rules, key=lambda item: item.rule_id):
            canonical_items.append(
                {
                    "id": r.rule_id,
                    "statement": r.statement.strip(),
                    "status": r.status.value,
                    "confidence": round(r.confidence, 4),
                }
            )

        payload = json.dumps(canonical_items, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
