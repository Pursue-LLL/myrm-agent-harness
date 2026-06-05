"""Circuit breaker for browser pool domain failures.


[INPUT]
- asyncio (POS: Python async programming)
- time (POS: Python time module)
- collections::defaultdict (POS: Python dict)
- urllib.parse::urlparse (POS: URL parsing)

[OUTPUT]
- CircuitBreakerOpenError: circuit breaker open exception
- CircuitBreakerCallback: circuit breaker callback protocol
- CircuitBreaker: circuit breaker

[POS]
Circuit breaker module. Prevents persistently failing domains from degrading the entire system.
Opens the circuit breaker when a domain's consecutive failure count exceeds the threshold, rejecting requests to that domain.
Automatically recovers after a timeout period.
Supports state change callbacks (on_open/on_close) for real-time monitoring and alerting.
"""

import logging
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Protocol, TypeVar
from urllib.parse import urlparse

_T = TypeVar("_T")
_logger = logging.getLogger(__name__)


class CircuitBreakerOpenError(Exception):
    """熔断器打开Exception（Domain被熔断）."""


class CircuitBreakerCallback(Protocol):
    """熔断器回调Protocol.

    for 监听熔断器State变化，Support实时告警 and 监控。
    """

    def on_open(self, domain: str, failure_count: int) -> None:
        """熔断器打开时回调.

        Args:
            domain: 被熔断 Domain
            failure_count: Failure次数

        """
        ...

    def on_close(self, domain: str) -> None:
        """熔断器Close时回调（TimeoutAutoRestore to CLOSED）.

        Args:
            domain: Restore Domain

        """
        ...


class LoggingCallback:
    """DefaultLog回调implements."""

    def on_open(self, domain: str, failure_count: int) -> None:
        _logger.warning(f"Circuit breaker OPENED for domain '{domain}' after {failure_count} failures")

    def on_close(self, domain: str) -> None:
        _logger.info(f"Circuit breaker CLOSED for domain '{domain}' (recovered)")


class CircuitBreaker:
    """熔断器 -  prevent 持续Failure Domain拖垮系统.

    State机：
    - CLOSED（Close）：normal工作，RecordFailure次数
    - OPEN（打开）：达 to Failure阈Value，拒绝Request；Timeout后Auto转 is CLOSED
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        timeout: float = 60.0,
        callback: CircuitBreakerCallback | None = None,
    ) -> None:
        """Initialize熔断器.

        Args:
            failure_threshold: 连续Failure次数阈Value
            timeout: 熔断器打开后 Timeout时间（秒）
            callback: State变化回调（optional，Default using LoggingCallback）

        """
        self._failure_threshold = failure_threshold
        self._timeout = timeout
        self.callback = callback or LoggingCallback()  # 公开Property， allow 替换

        self._failure_counts: defaultdict[str, int] = defaultdict(int)
        self._open_until: dict[str, float] = {}

    def _extract_domain(self, url: str) -> str:
        """ExtractURL Domain."""
        parsed = urlparse(url)
        return parsed.netloc or url

    def _is_open(self, domain: str) -> bool:
        """Check熔断器Whether打开."""
        if domain not in self._open_until:
            return False

        # CheckWhetherTimeout（Auto转 is CLOSED）
        if time.time() >= self._open_until[domain]:
            del self._open_until[domain]
            self._failure_counts[domain] = 0
            self.callback.on_close(domain)
            return False

        return True

    async def call(self, url: str, func: Callable[[], Awaitable[_T]]) -> _T:
        """via 熔断器ExecuteFunction.

        Args:
            url: 目标URL
            func: AsyncFunction

        Returns:
            FunctionExecuteResult

        Raises:
            CircuitBreakerOpenError: 熔断器打开时拒绝Request

        """
        domain = self._extract_domain(url)

        # Check熔断器State
        if self._is_open(domain):
            msg = f"Circuit breaker is OPEN for domain: {domain}"
            raise CircuitBreakerOpenError(msg)

        try:
            result = await func()
            self._on_success(domain)
            return result
        except Exception:
            self._on_failure(domain)
            raise

    def _on_success(self, domain: str) -> None:
        """RecordSuccessCall，ResetFailure计数."""
        self._failure_counts[domain] = 0

    def _on_failure(self, domain: str) -> None:
        """RecordFailureCall."""
        self._failure_counts[domain] += 1

        # CheckWhether达 to Failure阈Value
        if self._failure_counts[domain] >= self._failure_threshold:
            failure_count = self._failure_counts[domain]

            # 打开熔断器（CLOSED → OPEN）
            self._open_until[domain] = time.time() + self._timeout
            self._failure_counts[domain] = 0
            self.callback.on_open(domain, failure_count)

    _GLOBAL_CRASH_DOMAIN = "__browser_crash__"

    def record_failure(self, url: str | None = None) -> None:
        """Record a failure for the given URL or global browser crash.

        When called without arguments (from CrashWatchdogMixin on browser crash),
        uses a synthetic domain to track browser-level failures.
        """
        domain = self._extract_domain(url) if url else self._GLOBAL_CRASH_DOMAIN
        self._on_failure(domain)

    def get_state(self, url: str) -> str:
        """Get熔断器State.

        Returns:
            "CLOSED" | "OPEN"

        """
        domain = self._extract_domain(url)
        return "OPEN" if self._is_open(domain) else "CLOSED"

    def reset(self, url: str | None = None) -> None:
        """Reset熔断器State.

        Args:
            url: 目标URL，If is None则ResetAll

        """
        if url is None:
            self._failure_counts.clear()
            self._open_until.clear()
        else:
            domain = self._extract_domain(url)
            self._failure_counts.pop(domain, None)
            self._open_until.pop(domain, None)

    @property
    def stats(self) -> dict[str, object]:
        """Get熔断器Statisticsinformation."""
        now = time.time()
        return {
            "open_circuits": len(self._open_until),
            "domains_with_failures": len([c for c in self._failure_counts.values() if c > 0]),
            "open_domains": list(self._open_until.keys()),
            "open_until": {
                domain: remaining for domain, until in self._open_until.items() if (remaining := until - now) > 0
            },
        }
