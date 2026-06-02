"""Nonce Manager — Anti-replay attack core component.

Nonce (Number used once) prevents request replay attacks.
Uses time-ordered in-memory storage with TTL-based expiration.

In Agent-in-Sandbox architecture each sandbox runs an independent
single-user Server instance — no cross-instance sharing needed,
in-memory storage is sufficient.

Security constraints:
- Nonce length: 32-128 bytes (prevents DOS via oversized nonces)
- TTL-based expiration (prevents unbounded memory growth)

[INPUT]
- (none)

[OUTPUT]
- NonceManager: class — Nonce Manager

[POS]
Provides NonceManager.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict

logger = logging.getLogger(__name__)


class NonceManager:
    """Nonce manager with TTL-based expiration (memory storage)."""

    MIN_NONCE_LENGTH = 32
    MAX_NONCE_LENGTH = 128
    _MAX_STORE_SIZE = 10000

    def __init__(self, ttl: int = 120) -> None:
        self._ttl = ttl
        self._store: OrderedDict[str, float] = OrderedDict()
        self._lock = asyncio.Lock()

    async def check_and_store(self, nonce: str) -> bool:
        """Check and store a nonce.

        Returns:
            True: Nonce is valid (first use)
            False: Nonce rejected (replay / invalid format)
        """
        if not nonce:
            logger.warning("Nonce is empty")
            return False

        nonce_length = len(nonce.encode("utf-8"))
        if nonce_length < self.MIN_NONCE_LENGTH:
            logger.warning(
                "Nonce too short: %d < %d", nonce_length, self.MIN_NONCE_LENGTH
            )
            return False
        if nonce_length > self.MAX_NONCE_LENGTH:
            logger.warning(
                "Nonce too long: %d > %d", nonce_length, self.MAX_NONCE_LENGTH
            )
            return False

        now = time.monotonic()

        async with self._lock:
            self._evict_expired(now)

            if nonce in self._store:
                logger.warning("Nonce replay detected: %s...", nonce[:16])
                return False

            self._store[nonce] = now

            if len(self._store) > self._MAX_STORE_SIZE:
                evict_count = len(self._store) - self._MAX_STORE_SIZE
                for _ in range(evict_count):
                    self._store.popitem(last=False)
                logger.warning(
                    "Nonce store hard limit reached, evicted %d oldest entries",
                    evict_count,
                )

            return True

    def _evict_expired(self, now: float) -> None:
        """Remove nonces older than TTL (O(k) where k = expired count)."""
        cutoff = now - self._ttl
        while self._store:
            _oldest_nonce, oldest_time = next(iter(self._store.items()))
            if oldest_time > cutoff:
                break
            self._store.popitem(last=False)

    async def cleanup(self) -> None:
        """Release all resources."""
        async with self._lock:
            self._store.clear()

    async def get_stats(self) -> dict[str, int | str]:
        """Get current statistics."""
        return {
            "total_nonces": len(self._store),
            "ttl_seconds": self._ttl,
            "storage_type": "memory",
        }


nonce_manager = NonceManager()

__all__ = ["NonceManager", "nonce_manager"]
