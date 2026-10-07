"""[POS]: src/myrm_agent_harness/toolkits/memory/repair/barrier.py
[INPUT]: Active session snapshot state and pending pruning mutation requests.
[OUTPUT]: Cache-preserving compaction guard preventing prompt cache invalidation.
"""

import hashlib
import time


class CachePreservingCompactionBarrier:
    """Guard barrier protecting prompt prefix caches from jitter caused by memory mutations."""

    def __init__(self) -> None:
        # session_id -> frozen_snapshot_hash
        self._active_snapshots: dict[str, str] = {}
        # session_id -> list of pending archived memory ids
        self._deferred_compactions: dict[str, list[str]] = {}
        # session_id -> last_active_epoch
        self._session_activity: dict[str, float] = {}

    def register_session_snapshot(self, session_id: str, prompt_prefix: str) -> str:
        """Register and freeze a prompt prefix hash for an active session."""
        snapshot_hash = hashlib.sha256(prompt_prefix.encode("utf-8")).hexdigest()
        self._active_snapshots[session_id] = snapshot_hash
        self._session_activity[session_id] = time.time()
        if session_id not in self._deferred_compactions:
            self._deferred_compactions[session_id] = []
        return snapshot_hash

    def is_session_active(self, session_id: str, timeout_seconds: float = 3600.0) -> bool:
        """Check whether a session is currently active and within TTL."""
        if session_id not in self._session_activity:
            return False
        last_active = self._session_activity[session_id]
        return (time.time() - last_active) < timeout_seconds

    def can_compact_safely(self, session_id: str) -> bool:
        """Determine if pruning mutations can be committed immediately without busting cache."""
        return not self.is_session_active(session_id)

    def defer_compaction_if_active(self, session_id: str, memory_ids: list[str]) -> bool:
        """Defer pruning mutations if session is active; return True if deferred."""
        if self.is_session_active(session_id):
            if session_id not in self._deferred_compactions:
                self._deferred_compactions[session_id] = []
            self._deferred_compactions[session_id].extend(memory_ids)
            return True
        return False

    def release_session(self, session_id: str) -> list[str]:
        """Release session snapshot lock and return any deferred pruned memory IDs."""
        self._active_snapshots.pop(session_id, None)
        self._session_activity.pop(session_id, None)
        return self._deferred_compactions.pop(session_id, [])

    def get_snapshot_hash(self, session_id: str) -> str | None:
        """Retrieve frozen snapshot hash for the given session."""
        return self._active_snapshots.get(session_id)
