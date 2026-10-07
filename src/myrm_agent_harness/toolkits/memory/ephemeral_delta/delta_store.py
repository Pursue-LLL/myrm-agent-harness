# [POS]: src/myrm_agent_harness/toolkits/memory/ephemeral_delta/delta_store.py
# [INPUT]: src/myrm_agent_harness/toolkits/memory/ephemeral_delta/models.py
# [OUTPUT]: EphemeralDeltaStore

from __future__ import annotations

import logging
from collections import defaultdict

from myrm_agent_harness.toolkits.memory.ephemeral_delta.models import (
    DeltaActionKind,
    EphemeralDeltaBufferSnapshot,
    EphemeralDeltaItem,
)

logger = logging.getLogger(__name__)


class EphemeralDeltaStore:
    """In-memory, session-scoped transient buffer for prompt-cache-preserving deltas.

    Ensures zero mutations to frozen SystemPrompt while holding turn-level
    corrections in memory, maintaining high recency awareness for agent inference.
    """

    def __init__(self) -> None:
        self._buffers: dict[str, list[EphemeralDeltaItem]] = defaultdict(list)
        self._frozen_snapshots: dict[str, str] = {}
        self._reconciled_flags: dict[str, bool] = defaultdict(bool)

    def bind_frozen_snapshot(self, session_id: str, snapshot_id: str) -> None:
        """Bind a frozen baseline memory snapshot ID to this session."""
        self._frozen_snapshots[session_id] = snapshot_id

    def record_delta(
        self,
        session_id: str,
        delta: EphemeralDeltaItem,
    ) -> EphemeralDeltaItem:
        """Record an ephemeral delta into the session buffer."""
        self._buffers[session_id].append(delta)
        self._reconciled_flags[session_id] = False
        logger.debug(
            "Recorded delta %s for session %s (key=%s, action=%s)",
            delta.delta_id,
            session_id,
            delta.target_key,
            delta.action,
        )
        return delta

    def get_all_raw_deltas(self, session_id: str) -> list[EphemeralDeltaItem]:
        """Return the un-compacted chronological history of deltas for this session."""
        return list(self._buffers.get(session_id, []))

    def compact_deltas(self, session_id: str) -> list[EphemeralDeltaItem]:
        """Apply Last-Write-Wins (LWW) conflict resolution across deltas by target_key.

        Rules:
        1. If multiple deltas target the same key, only the latest delta applies.
        2. If the latest delta is RETRACT, the target is suppressed from active prompt injections.
        3. Returns an ordered list of actively applicable deltas.
        """
        raw_list = self._buffers.get(session_id, [])
        if not raw_list:
            return []

        latest_by_key: dict[str, EphemeralDeltaItem] = {}
        for item in raw_list:
            latest_by_key[item.target_key] = item

        active_deltas: list[EphemeralDeltaItem] = []
        for key in sorted(latest_by_key.keys()):
            item = latest_by_key[key]
            if item.action != DeltaActionKind.RETRACT:
                active_deltas.append(item)

        return active_deltas

    def get_active_deltas(self, session_id: str) -> list[EphemeralDeltaItem]:
        """Return active, non-retracted deltas after LWW deduplication."""
        return self.compact_deltas(session_id)

    def get_snapshot(self, session_id: str) -> EphemeralDeltaBufferSnapshot:
        """Generate a snapshot of the current delta buffer status."""
        active = self.get_active_deltas(session_id)
        total_chars = sum(len(d.content) for d in active)
        return EphemeralDeltaBufferSnapshot(
            session_id=session_id,
            deltas=active,
            frozen_snapshot_id=self._frozen_snapshots.get(session_id),
            total_chars=total_chars,
            is_reconciled=self._reconciled_flags.get(session_id, False),
        )

    def mark_reconciled(self, session_id: str) -> None:
        """Mark the session's active deltas as reconciled into permanent storage."""
        self._reconciled_flags[session_id] = True

    def clear(self, session_id: str) -> None:
        """Clear the buffer for a session."""
        self._buffers.pop(session_id, None)
        self._frozen_snapshots.pop(session_id, None)
        self._reconciled_flags.pop(session_id, None)
