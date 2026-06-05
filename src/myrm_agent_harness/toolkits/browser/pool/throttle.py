"""Navigation throttle strategies.


[INPUT]
- asyncio (POS: Python async programming)
- time::time (POS: Python timestamp)
- random::uniform (POS: Python random number)
- urllib.parse::urlparse (POS: URL parsing)
- collections::defaultdict (POS: Python default dict)
- typing::Protocol (POS: Python protocol)
- .config::RateLimiterConfig (POS: rate limiter config)

[OUTPUT]
- ThrottleStrategy: throttle strategy protocol
- NoThrottle: no-throttle implementation (local mode)
- DomainThrottle: per-domain throttling (Token Bucket algorithm)
- create_throttle_strategy: factory function (creates strategy based on config)

[POS]
Throttle strategy module. Defines the throttle protocol and two implementations, supports domain-level QPS control.
Used by Navigator, called via before_navigate() before navigation.
"""

import asyncio
import logging
import random
from collections import defaultdict
from time import time
from typing import Protocol
from urllib.parse import urlparse

from .config import RateLimiterConfig, ThrottleMode

_logger = logging.getLogger(__name__)


class ThrottleStrategy(Protocol):
    """限流StrategyProtocol."""

    async def before_navigate(self, url: str) -> None:
        """导航前Wait（限流控制）."""
        ...

    def record_response(self, url: str, success: bool) -> None:
        """Record导航Result（供StrategyimplementsStatistics or extended；Current DomainThrottle  no Statedepends on）."""
        ...


class NoThrottle:
    """no 限流（LocalMode/开发Mode）."""

    async def before_navigate(self, url: str) -> None:
        pass

    def record_response(self, url: str, success: bool) -> None:
        pass


class DomainThrottle:
    """按Domain限流（Token Bucket 算法 + 随机抖动）."""

    def __init__(self, config: RateLimiterConfig) -> None:
        self._max_qps = config.domain_qps
        self._burst_size = config.domain_burst
        self._refill_interval = 1.0 / self._max_qps

        self._buckets: defaultdict[str, dict[str, float]] = defaultdict(
            lambda: {"tokens": self._burst_size, "last_refill": time()},
        )
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def before_navigate(self, url: str) -> None:
        domain = urlparse(url).netloc or "unknown"
        async with self._locks[domain]:
            bucket = self._buckets[domain]
            now = time()

            elapsed = now - bucket["last_refill"]
            refill_count = int(elapsed / self._refill_interval)
            if refill_count > 0:
                bucket["tokens"] = min(self._burst_size, bucket["tokens"] + refill_count)
                bucket["last_refill"] += refill_count * self._refill_interval

            if bucket["tokens"] < 1:
                wait_time = self._refill_interval + random.uniform(0, 0.1)
                _logger.debug(
                    "Navigation throttle wait before domain request",
                    extra={"domain": domain, "wait_seconds": round(wait_time, 4)},
                )
                await asyncio.sleep(wait_time)
                bucket["tokens"] = 1
                bucket["last_refill"] = time()

            bucket["tokens"] -= 1

    def record_response(self, url: str, success: bool) -> None:
        pass


def create_throttle_strategy(config: RateLimiterConfig) -> ThrottleStrategy:
    """工厂Function： based on ConfigureCreate限流Strategy."""
    if config.mode == ThrottleMode.NONE:
        return NoThrottle()
    if config.mode == ThrottleMode.DOMAIN:
        return DomainThrottle(config)
    msg = f"Unknown throttle mode: {config.mode}"
    raise ValueError(msg)
