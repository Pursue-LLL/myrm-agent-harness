"""Rate limiting for brute-force protection.

Provides sliding-window rate limiter with per-key + global counters
to defend against single-IP and distributed brute-force attacks.

[INPUT]
- (none — pure data + logic module)

[OUTPUT]
- RateLimiter — abstract base class
- MemoryRateLimiter — in-memory backend (default)

[POS]
Agent security rate limiter. Prevents brute-force attacks (e.g., WebUI login) with configurable rate limiting.

"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Protocol

logger = logging.getLogger(__name__)


@dataclass
class RateLimitConfig:
    """Rate limiter configuration.

    Attributes:
        max_attempts_per_key: Max attempts per key (e.g., IP) in window
        max_attempts_global: Max total attempts (all keys) in window
        window_seconds: Time window duration (seconds)
        cleanup_interval_seconds: Cleanup interval for stale entries (seconds)
    """

    max_attempts_per_key: int = 5
    max_attempts_global: int = 100
    window_seconds: int = 60
    cleanup_interval_seconds: int = 300


@dataclass
class RateLimitEntry:
    """Rate limit tracking entry for a single key."""

    attempts: int
    window_start: float


class RateLimitResult(Protocol):
    """Result of a rate limit check."""

    allowed: bool
    retry_after_seconds: int | None


@dataclass
class _RateLimitResult:
    """Concrete implementation of RateLimitResult."""

    allowed: bool
    retry_after_seconds: int | None = None


class RateLimiter(ABC):
    """Abstract rate limiter with per-key + global sliding-window tracking.

    Defends against:
    - Single-IP brute-force: per-key limit (e.g., 5 attempts/60s per IP)
    - Distributed brute-force: global limit (e.g., 100 attempts/60s total)

    Implementations:
    - MemoryRateLimiter: In-memory backend (default, suitable for single-instance)
    """

    def __init__(self, config: RateLimitConfig | None = None) -> None:
        self.config = config or RateLimitConfig()
        self._cleanup_task: asyncio.Task[None] | None = None

    @abstractmethod
    async def check(self, key: str) -> RateLimitResult:
        """Check if the request is allowed for the given key.

        Args:
            key: Rate limit key (e.g., IP address, user ID)

        Returns:
            RateLimitResult with allowed flag and retry_after_seconds
        """
        ...

    @abstractmethod
    async def _cleanup_stale_entries(self) -> None:
        """Cleanup stale entries to prevent memory leak.

        Called periodically by background task.
        """
        ...

    async def start_cleanup_task(self) -> None:
        """Start background cleanup task.

        Should be called once at service startup.
        """
        if self._cleanup_task is not None:
            logger.warning("Cleanup task already running")
            return

        async def _cleanup_loop() -> None:
            while True:
                await asyncio.sleep(self.config.cleanup_interval_seconds)
                try:
                    await self._cleanup_stale_entries()
                except Exception as e:
                    logger.exception("Rate limiter cleanup failed: %s", e)

        self._cleanup_task = asyncio.create_task(_cleanup_loop())
        logger.info("Rate limiter cleanup task started (interval=%ds)", self.config.cleanup_interval_seconds)

    async def stop_cleanup_task(self) -> None:
        """Stop background cleanup task.

        Should be called at service shutdown.
        """
        if self._cleanup_task is None:
            return

        self._cleanup_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._cleanup_task
        self._cleanup_task = None
        logger.info("Rate limiter cleanup task stopped")


class MemoryRateLimiter(RateLimiter):
    """In-memory rate limiter with sliding-window tracking.

    Concurrency-safe for async contexts (uses asyncio.Lock).
    Suitable for single-instance deployments (Agent-in-Sandbox).
    """

    def __init__(self, config: RateLimitConfig | None = None) -> None:
        super().__init__(config)
        self._entries: dict[str, RateLimitEntry] = {}
        self._global_attempts = 0
        self._global_window_start = time.time()
        self._lock = asyncio.Lock()

    async def check(self, key: str) -> RateLimitResult:
        """Check if the request is allowed for the given key.

        Applies per-key + global sliding-window rate limits.
        Uses asyncio.Lock to prevent race conditions in concurrent access.
        """
        now = time.time()

        async with self._lock:
            # Reset global window if expired
            if now - self._global_window_start > self.config.window_seconds:
                self._global_attempts = 0
                self._global_window_start = now

            # Global rate limit — blocks all keys if too many total attempts
            self._global_attempts += 1
            if self._global_attempts > self.config.max_attempts_global:
                retry_after = int(self.config.window_seconds - (now - self._global_window_start))
                logger.warning(
                    "Global rate limit exceeded: %d attempts in %ds window",
                    self._global_attempts,
                    self.config.window_seconds,
                )
                return _RateLimitResult(allowed=False, retry_after_seconds=max(1, retry_after))

            # Per-key rate limit
            entry = self._entries.get(key)

            if entry is None or now - entry.window_start > self.config.window_seconds:
                # New window
                self._entries[key] = RateLimitEntry(attempts=1, window_start=now)
                return _RateLimitResult(allowed=True)

            # Within window
            entry.attempts += 1
            if entry.attempts > self.config.max_attempts_per_key:
                retry_after = int(self.config.window_seconds - (now - entry.window_start))
                logger.warning(
                    "Per-key rate limit exceeded: key=%s, %d attempts in %ds window",
                    key,
                    entry.attempts,
                    self.config.window_seconds,
                )
                return _RateLimitResult(allowed=False, retry_after_seconds=max(1, retry_after))

            return _RateLimitResult(allowed=True)

    async def reset(self, key: str) -> None:
        """Reset rate limit for a specific key (e.g., after successful CAPTCHA).

        Args:
            key: Rate limit key to reset (e.g., IP address)
        """
        async with self._lock:
            if key in self._entries:
                del self._entries[key]
                logger.info("Rate limit reset for key: %s", key)

    async def _cleanup_stale_entries(self) -> None:
        """Cleanup entries older than 2x window.

        Prevents memory leak from accumulating stale IP records.
        Uses asyncio.Lock to prevent race conditions during cleanup.
        """
        now = time.time()
        stale_threshold = self.config.window_seconds * 2

        async with self._lock:
            stale_keys = [key for key, entry in self._entries.items() if now - entry.window_start > stale_threshold]

            for key in stale_keys:
                del self._entries[key]

        if stale_keys:
            logger.debug("Cleaned up %d stale rate limit entries", len(stale_keys))
