"""[POS]: src/myrm_agent_harness/toolkits/memory/noise_free_extractor/epoch_manager.py
[INPUT]: User identifier and observed generation epochs from asynchronous extractions.
[OUTPUT]: PurgeGenerationEpochManager enforcing thread-safe monotonic epoch fencing.

Reference: Anthropic Commerce Agents (commerce_common/memory.py:purge_user).
Prevents stale asynchronous background writes from resurrecting memories that a user
explicitly purged during an ongoing extraction turn.
"""

from datetime import UTC, datetime
from threading import Lock

from .types import PurgeEpochStatus


class PurgeGenerationEpochManager:
    """Manages monotonic purge generations per user namespace."""

    def __init__(self) -> None:
        self._lock = Lock()
        # user_id -> current generation (starts at 1)
        self._user_generations: dict[str, int] = {}
        # user_id -> count of dropped stale writes
        self._stale_drops: dict[str, int] = {}
        # user_id -> last purge ISO timestamp
        self._last_purged_at: dict[str, str] = {}
        # user_id -> count of active asynchronous extractions
        self._active_extractions: dict[str, int] = {}
        # user_id -> count of blocked PII attempts
        self._pii_blocked_counts: dict[str, int] = {}

    def get_generation(self, user_id: str) -> int:
        """Get the current epoch generation for the user (defaults to 1)."""
        with self._lock:
            return self._user_generations.setdefault(user_id, 1)

    def bump_generation_on_purge(self, user_id: str) -> int:
        """Atomically bump the user's purge generation upon an explicit purge/forget call.

        Returns the newly advanced generation. All background tasks observing prior
        generations will have their writes discarded.
        """
        with self._lock:
            current = self._user_generations.setdefault(user_id, 1)
            new_generation = current + 1
            self._user_generations[user_id] = new_generation
            self._last_purged_at[user_id] = datetime.now(UTC).isoformat()
            return new_generation

    def start_extraction_task(self, user_id: str) -> int:
        """Register the start of an async extraction, returning the observed generation."""
        with self._lock:
            current = self._user_generations.setdefault(user_id, 1)
            self._active_extractions[user_id] = (
                self._active_extractions.get(user_id, 0) + 1
            )
            return current

    def finish_extraction_task(self, user_id: str) -> None:
        """Register completion of an async extraction."""
        with self._lock:
            active = self._active_extractions.get(user_id, 0)
            if active > 0:
                self._active_extractions[user_id] = active - 1

    def validate_and_fence_write(
        self, user_id: str, observed_generation: int
    ) -> bool:
        """Validate if a pending write is allowed or stale.

        Returns:
            True if write is strictly valid (observed_generation == current_generation).
            False if write is stale and must be dropped.
        """
        with self._lock:
            current = self._user_generations.setdefault(user_id, 1)
            if observed_generation < current:
                # Dropping stale write because a purge happened in between
                self._stale_drops[user_id] = self._stale_drops.get(user_id, 0) + 1
                return False
            return True

    def record_pii_violation(self, user_id: str) -> None:
        """Record a blocked PII attempt for auditing."""
        with self._lock:
            self._pii_blocked_counts[user_id] = (
                self._pii_blocked_counts.get(user_id, 0) + 1
            )

    def get_status(self, user_id: str, stored_facts_count: int = 0) -> PurgeEpochStatus:
        """Retrieve complete epoch status and fence statistics for user."""
        with self._lock:
            current = self._user_generations.setdefault(user_id, 1)
            return PurgeEpochStatus(
                user_id=user_id,
                current_generation=current,
                active_extractions=self._active_extractions.get(user_id, 0),
                stale_writes_dropped=self._stale_drops.get(user_id, 0),
                last_purged_at=self._last_purged_at.get(user_id),
                stored_facts_count=stored_facts_count,
                pii_violations_blocked=self._pii_blocked_counts.get(user_id, 0),
            )
