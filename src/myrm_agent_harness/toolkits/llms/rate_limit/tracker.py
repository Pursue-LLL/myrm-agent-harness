"""Rate Limit Tracker.

[INPUT]
- .types::RateLimitState (POS: Data structures)

[OUTPUT]
- RateLimitTracker: Thread-safe singleton for tracking rate limits.

[POS]
In-memory tracker for LLM provider rate limits.
"""

import threading

from .types import RateLimitState


class RateLimitTracker:
    """Thread-safe in-memory tracker for rate limits.

    Maintains the latest RateLimitState for each (provider, model) pair.
    Resolves race conditions using the updated_at timestamp.
    """

    _instance: "RateLimitTracker | None" = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._states: dict[tuple[str, str], RateLimitState] = {}
        self._state_lock = threading.RLock()

    @classmethod
    def get(cls) -> "RateLimitTracker":
        """Get the singleton instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def update(self, new_state: RateLimitState) -> bool:
        """Update the state if the new state is newer.

        Returns:
            True if updated, False if ignored (older timestamp).
        """
        key = (new_state.provider, new_state.model)
        with self._state_lock:
            current = self._states.get(key)
            if current is None or new_state.updated_at >= current.updated_at:
                self._states[key] = new_state
                return True
            return False

    def get_state(self, provider: str, model: str) -> RateLimitState | None:
        """Get the current state for a provider and model."""
        with self._state_lock:
            return self._states.get((provider, model))

    def get_all_states(self) -> list[RateLimitState]:
        """Get all tracked states."""
        with self._state_lock:
            return list(self._states.values())

    def can_consume(self, provider: str, model: str, tokens: int, requests: int = 1) -> bool:
        """Check if there is enough quota for the given provider and model."""
        state = self.get_state(provider, model)
        if not state:
            # If we don't have tracking data yet, assume we can consume
            return True
        return state.can_consume(tokens, requests)

    def clear(self) -> None:
        """Clear all tracked states (useful for testing)."""
        with self._state_lock:
            self._states.clear()
