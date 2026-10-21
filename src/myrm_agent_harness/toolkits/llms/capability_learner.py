"""In-process model capability learner.

Thread-safe singleton cache that records runtime-discovered model capabilities
(e.g., "rejects_media") so that subsequent requests skip known-bad operations
without an extra API roundtrip.

Designed as a lightweight, in-process store — no persistence layer needed.
Capability entries auto-expire after ``ttl_seconds`` to allow re-probing
when providers update model support.

[INPUT]
- (none — standalone module)

[OUTPUT]
- ModelCapabilityLearner: singleton model capability cache
- get_capability_learner(): module-level accessor

[POS]
Runtime model capability cache for proactive media filtering and error avoidance.
"""

from __future__ import annotations

import threading
import time


class ModelCapabilityLearner:
    """Thread-safe in-process cache for runtime-discovered model capabilities.

    Entries are keyed by ``(model_name, capability)`` and auto-expire
    after ``ttl_seconds`` (default 1 hour) so that stale learnings
    don't permanently block features a provider later enables.
    """

    _instance: ModelCapabilityLearner | None = None
    _lock = threading.Lock()

    DEFAULT_TTL = 3600  # 1 hour

    def __new__(cls) -> ModelCapabilityLearner:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    inst = super().__new__(cls)
                    inst._store: dict[tuple[str, str], tuple[object, float]] = {}
                    inst._store_lock = threading.Lock()
                    cls._instance = inst
        return cls._instance

    def learn(
        self,
        model_name: str,
        capability: str,
        value: object,
        *,
        ttl_seconds: int | None = None,
    ) -> None:
        """Record a learned capability for *model_name*.

        Args:
            model_name: Provider-qualified model identifier (e.g. "gpt-4o-mini").
            capability: Capability key (e.g. "rejects_media").
            value: Capability value (typically ``True`` / ``False``).
            ttl_seconds: Override default TTL for this entry.
        """
        ttl = ttl_seconds if ttl_seconds is not None else self.DEFAULT_TTL
        with self._store_lock:
            self._store[(model_name, capability)] = (value, time.monotonic() + ttl)

    def get(self, model_name: str, capability: str, default: object = None) -> object:
        """Retrieve a previously learned capability.

        Returns *default* if the capability was never learned or has expired.
        """
        key = (model_name, capability)
        with self._store_lock:
            entry = self._store.get(key)
            if entry is None:
                return default
            value, expires_at = entry
            if time.monotonic() > expires_at:
                del self._store[key]
                return default
            return value

    def clear(self) -> None:
        """Clear all learned capabilities (useful for tests)."""
        with self._store_lock:
            self._store.clear()

    def size(self) -> int:
        """Return current cache size (including expired but not yet evicted)."""
        with self._store_lock:
            return len(self._store)


def get_capability_learner() -> ModelCapabilityLearner:
    """Module-level accessor for the singleton learner."""
    return ModelCapabilityLearner()
