"""Per-domain rate limiter for deep_crawl operations.

Ensures responsible crawling by enforcing per-domain request intervals,
preventing anti-bot triggers and respecting server resources.

[INPUT]
- (none)

[OUTPUT]
- DomainRateLimiter: Async per-domain rate limiter with configurable intervals

[POS]
Per-domain rate limiter. Prevents aggressive crawling that triggers anti-bot
systems. Integrates with robots.txt Crawl-Delay when available.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict


class DomainRateLimiter:
    """Async per-domain rate limiter.

    Enforces minimum interval between requests to the same domain.
    Thread-safe within a single event loop (asyncio.Lock per domain).
    """

    def __init__(self, default_interval: float = 1.5, max_concurrent_per_domain: int = 2):
        """
        Args:
            default_interval: Minimum seconds between requests to same domain.
            max_concurrent_per_domain: Max concurrent requests to same domain.
        """
        self._default_interval = default_interval
        self._max_concurrent = max_concurrent_per_domain
        self._domain_intervals: dict[str, float] = {}
        self._last_request: dict[str, float] = defaultdict(float)
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._semaphores: dict[str, asyncio.Semaphore] = {}

    def set_domain_interval(self, domain: str, interval: float) -> None:
        """Override interval for a specific domain (e.g. from robots.txt Crawl-Delay)."""
        self._domain_intervals[domain] = max(interval, 0.5)

    def _get_interval(self, domain: str) -> float:
        return self._domain_intervals.get(domain, self._default_interval)

    def _get_semaphore(self, domain: str) -> asyncio.Semaphore:
        if domain not in self._semaphores:
            self._semaphores[domain] = asyncio.Semaphore(self._max_concurrent)
        return self._semaphores[domain]

    async def acquire(self, domain: str) -> None:
        """Wait until it's safe to make a request to this domain."""
        sem = self._get_semaphore(domain)
        await sem.acquire()

        async with self._locks[domain]:
            interval = self._get_interval(domain)
            elapsed = time.time() - self._last_request[domain]
            if elapsed < interval:
                await asyncio.sleep(interval - elapsed)
            self._last_request[domain] = time.time()

    def release(self, domain: str) -> None:
        """Release the semaphore slot for this domain."""
        sem = self._get_semaphore(domain)
        sem.release()
