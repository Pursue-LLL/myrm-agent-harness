"""Global probe throttle to prevent concurrent duplicate probes.

Prevents multiple concurrent requests from probing the same model simultaneously.

[INPUT]

[OUTPUT]
- GlobalProbeThrottle: Global probe throttler

[POS]
Global probe throttle. Prevents concurrent requests from redundantly probing the same model.
"""

from __future__ import annotations

import threading
import time


class GlobalProbeThrottle:
    """Global probe throttle for model fallback.

    Features:
    - Global throttling: Same model can only be probed once per interval across all requests
    - Thread-safe: Can be used from multiple concurrent requests
    - Memory bounded: Automatic cleanup of old entries

    Attributes:
        min_interval_ms: Minimum interval between probes for same model (default: 30s)
        ttl_ms: Time-to-live for probe records (default: 24 hours)
        max_entries: Maximum number of tracked models (default: 256)
    """

    def __init__(
        self,
        min_interval_ms: int = 30_000,
        ttl_ms: int = 24 * 60 * 60 * 1000,
        max_entries: int = 256,
    ) -> None:
        self.min_interval_ms = min_interval_ms
        self.ttl_ms = ttl_ms
        self.max_entries = max_entries
        self._last_probe: dict[str, float] = {}
        self._lock = threading.Lock()

    def should_probe(self, model_name: str, now_ms: float | None = None) -> bool:
        """Check if model should be probed (global throttle check).

        Args:
            model_name: Model identifier
            now_ms: Current timestamp in milliseconds (for testing, default: current time)

        Returns:
            True if probe is allowed (not throttled globally)
        """
        if now_ms is None:
            now_ms = time.time() * 1000

        with self._lock:
            # Cleanup expired entries
            self._prune_expired(now_ms)

            # Check if recently probed
            last_probe_ms = self._last_probe.get(model_name, 0)
            if now_ms - last_probe_ms < self.min_interval_ms:
                return False

            # Mark as probed
            self._last_probe[model_name] = now_ms

            # Enforce max entries
            self._enforce_max_entries()

            return True

    def _prune_expired(self, now_ms: float) -> None:
        """Remove expired entries.

        Args:
            now_ms: Current timestamp in milliseconds
        """
        cutoff = now_ms - self.ttl_ms
        expired_keys = [key for key, timestamp in self._last_probe.items() if timestamp < cutoff]
        for key in expired_keys:
            del self._last_probe[key]

    def _enforce_max_entries(self) -> None:
        """Enforce maximum number of tracked models by removing oldest."""
        while len(self._last_probe) > self.max_entries:
            # Find oldest entry
            oldest_key = min(self._last_probe, key=self._last_probe.get)  # type: ignore
            del self._last_probe[oldest_key]

    def clear(self) -> None:
        """Clear all entries (for testing)."""
        with self._lock:
            self._last_probe.clear()


# Global singleton instance
_global_throttle = GlobalProbeThrottle()


def get_global_probe_throttle() -> GlobalProbeThrottle:
    """Get global probe throttle singleton.

    Returns:
        Global probe throttle instance
    """
    return _global_throttle
