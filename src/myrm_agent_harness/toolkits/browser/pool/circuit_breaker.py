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
    """Raised when a domain is blocked by an open circuit breaker."""


class CircuitBreakerCallback(Protocol):
    """Circuit breaker callback protocol.

    Listens for circuit breaker state changes, enabling real-time alerting and monitoring.
    """

    def on_open(self, domain: str, failure_count: int) -> None:
        """Callback when the breaker opens.

        Args:
            domain: Domain that tripped the breaker.
            failure_count: Number of consecutive failures.

        """
        ...

    def on_close(self, domain: str) -> None:
        """Callback when the breaker closes (auto-recovered after timeout).

        Args:
            domain: Recovered domain.

        """
        ...


class LoggingCallback:
    """Default logging callback implementation."""

    def on_open(self, domain: str, failure_count: int) -> None:
        _logger.warning(f"Circuit breaker OPENED for domain '{domain}' after {failure_count} failures")

    def on_close(self, domain: str) -> None:
        _logger.info(f"Circuit breaker CLOSED for domain '{domain}' (recovered)")


class CircuitBreaker:
    """Circuit breaker — prevents a persistently failing domain from dragging the system down.

    State machine:
    - CLOSED: normal operation, records failure counts.
    - OPEN: failure threshold reached, requests rejected; auto-transitions to CLOSED after timeout.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        timeout: float = 60.0,
        callback: CircuitBreakerCallback | None = None,
    ) -> None:
        """Initialize the circuit breaker.

        Args:
            failure_threshold: Consecutive failure count threshold.
            timeout: Time (seconds) the breaker stays open.
            callback: State-change callback (optional, defaults to LoggingCallback).

        """
        self._failure_threshold = failure_threshold
        self._timeout = timeout
        self.callback = callback or LoggingCallback()  # public property, allows replacement

        self._failure_counts: defaultdict[str, int] = defaultdict(int)
        self._open_until: dict[str, float] = {}

    def _extract_domain(self, url: str) -> str:
        """Extract the domain from a URL."""
        parsed = urlparse(url)
        return parsed.netloc or url

    def _is_open(self, domain: str) -> bool:
        """Check whether the breaker is open."""
        if domain not in self._open_until:
            return False

        # Check for timeout (auto-transition to CLOSED)
        if time.time() >= self._open_until[domain]:
            del self._open_until[domain]
            self._failure_counts[domain] = 0
            self.callback.on_close(domain)
            return False

        return True

    async def call(self, url: str, func: Callable[[], Awaitable[_T]]) -> _T:
        """Execute a function through the circuit breaker.

        Args:
            url: Target URL.
            func: Async function.

        Returns:
            Function execution result.

        Raises:
            CircuitBreakerOpenError: request rejected while the breaker is open.

        """
        domain = self._extract_domain(url)

        # Check breaker state
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
        """Record a successful call, resetting the failure count."""
        self._failure_counts[domain] = 0

    def _on_failure(self, domain: str) -> None:
        """Record a failed call."""
        self._failure_counts[domain] += 1

        # Check whether the failure threshold is reached
        if self._failure_counts[domain] >= self._failure_threshold:
            failure_count = self._failure_counts[domain]

            # Open the breaker (CLOSED → OPEN)
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
        """Get the circuit breaker state.

        Returns:
            "CLOSED" | "OPEN"

        """
        domain = self._extract_domain(url)
        return "OPEN" if self._is_open(domain) else "CLOSED"

    def reset(self, url: str | None = None) -> None:
        """Reset the circuit breaker state.

        Args:
            url: Target URL; when None, resets all domains.

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
        """Get circuit breaker statistics."""
        now = time.time()
        return {
            "open_circuits": len(self._open_until),
            "domains_with_failures": len([c for c in self._failure_counts.values() if c > 0]),
            "open_domains": list(self._open_until.keys()),
            "open_until": {
                domain: remaining for domain, until in self._open_until.items() if (remaining := until - now) > 0
            },
        }
