"""Proxy rotation with sticky session support.

[OUTPUT]
- ProxyConfig: frozen dataclass for a single proxy server
- ProxyPool: Protocol for proxy pool strategies
- RoundRobinProxyPool: Default implementation with round-robin rotation and sticky sessions

[POS]
Manages proxy rotation across Browser Pool and FetchEngine. Supports:
1. Round-robin rotation across multiple proxies
2. Sticky sessions (same proxy for a given session_id with TTL)
3. Concurrency-safe in asyncio single-threaded event loop
4. Exponential backoff quarantine (60s → 300s → 3600s) on proxy failures
5. Automatic expired session cleanup (via lifecycle tick)
"""

from __future__ import annotations

import itertools
import logging
import time
from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class ProxyPoolExhaustedError(Exception):
    """Raised when all proxies in the pool are quarantined/exhausted."""

    pass


@dataclass(frozen=True, slots=True)
class ProxyConfig:
    """Immutable proxy server configuration."""

    server: str
    username: str | None = None
    password: str | None = None

    def to_url(self) -> str:
        """Convert to URL string for httpx/Scrapling (e.g. http://user:pass@host:port)."""
        if self.username and self.password:
            parsed = urlparse(self.server)
            host = f"{parsed.hostname}:{parsed.port}" if parsed.port else str(parsed.hostname)
            return f"{parsed.scheme}://{self.username}:{self.password}@{host}"
        return self.server

    def to_playwright_dict(self) -> dict[str, str]:
        """Convert to Patchright/Playwright proxy dict format.

        Returns dict with 'server' and optionally 'username'/'password'.
        Only includes non-None fields.
        """
        result: dict[str, str] = {"server": self.server}
        if self.username:
            result["username"] = self.username
        if self.password:
            result["password"] = self.password
        return result

    @staticmethod
    def from_url(url: str) -> ProxyConfig:
        """Parse proxy URL (e.g. http://user:pass@host:port) into ProxyConfig."""
        parsed = urlparse(url)
        if parsed.username:
            host = f"{parsed.hostname}:{parsed.port}" if parsed.port else str(parsed.hostname)
            server = f"{parsed.scheme}://{host}"
            return ProxyConfig(server=server, username=parsed.username, password=parsed.password)
        return ProxyConfig(server=url)


@dataclass(slots=True)
class _StickyEntry:
    """Internal: tracks a sticky session binding."""

    proxy: ProxyConfig
    created_at: float
    ttl: int


@runtime_checkable
class ProxyPool(Protocol):
    """Abstract proxy pool interface.

    Implementations must be concurrency-safe (asyncio single-threaded is sufficient).
    """

    def get_next(self) -> ProxyConfig:
        """Get next proxy via rotation strategy."""
        ...

    def get_for_session(self, session_id: str, ttl: int = 3600) -> ProxyConfig:
        """Get proxy for a session (creates binding if not exists)."""
        ...

    def release_session(self, session_id: str) -> None:
        """Release a sticky session binding."""
        ...

    def report_failure(self, session_id: str, quarantine_seconds: int = 300) -> None:
        """Report a proxy failure for a session, quarantining the proxy and releasing the session."""
        ...

    @property
    def active_session_count(self) -> int:
        """Number of active sticky sessions."""
        ...

    def cleanup_expired_sessions(self) -> int:
        """Remove expired sticky sessions. Returns number of cleaned sessions."""
        ...


class RoundRobinProxyPool:
    """Round-robin proxy rotation with sticky session support.

    Concurrency model: all methods are synchronous and safe in asyncio
    single-threaded event loop (no await points, no preemption).
    """

    def __init__(self, proxies: list[ProxyConfig]) -> None:
        if not proxies:
            raise ValueError("proxies list must not be empty")
        self._proxies = tuple(proxies)
        self._cycle = itertools.cycle(self._proxies)
        self._sessions: dict[str, _StickyEntry] = {}
        self._quarantine: dict[ProxyConfig, float] = {}  # proxy -> expire_time
        self._failure_counts: dict[ProxyConfig, int] = {}  # proxy -> consecutive_failures

    def get_next(self) -> ProxyConfig:
        """Get next proxy in round-robin order, skipping quarantined ones.

        Raises:
            ProxyPoolExhaustedError: If all proxies are currently quarantined.
        """
        now = time.monotonic()
        # Clean up expired quarantine entries
        expired_q = [p for p, exp in self._quarantine.items() if now >= exp]
        for p in expired_q:
            del self._quarantine[p]
            # DO NOT reset failure count here, we want exponential backoff to persist across failures
            # We only reset it if the proxy succeeds (which we don't track explicitly here)
            # or we could add a success reporting mechanism, but for now we keep the failure count
            # so repeated failures keep increasing the backoff.

        # Try to find a non-quarantined proxy (up to len(proxies) attempts)
        for _ in range(len(self._proxies)):
            proxy = next(self._cycle)
            if proxy not in self._quarantine:
                return proxy

        # If all are quarantined, raise error to trigger higher-level backoff
        logger.error("All %d proxies are currently quarantined.", len(self._proxies))
        raise ProxyPoolExhaustedError("All proxies in the pool are currently quarantined.")

    def get_for_session(self, session_id: str, ttl: int = 3600) -> ProxyConfig:
        """Get or create a sticky session binding.

        If session exists and not expired, returns same proxy.
        If expired or new, assigns next proxy from rotation.
        TTL is fixed from creation time (not refreshed on access).
        """
        entry = self._sessions.get(session_id)
        if entry is not None:
            if time.monotonic() - entry.created_at < entry.ttl:
                return entry.proxy
            del self._sessions[session_id]

        proxy = self.get_next()
        self._sessions[session_id] = _StickyEntry(proxy=proxy, created_at=time.monotonic(), ttl=ttl)
        return proxy

    def release_session(self, session_id: str) -> None:
        """Release a sticky session binding."""
        self._sessions.pop(session_id, None)

    def report_failure(self, session_id: str, base_quarantine_seconds: int = 60) -> None:
        """Report a proxy failure for a session.

        Quarantines the proxy using exponential backoff based on consecutive failures,
        and releases the session binding.
        """
        entry = self._sessions.pop(session_id, None)
        if entry is not None:
            proxy = entry.proxy
            failures = self._failure_counts.get(proxy, 0) + 1
            self._failure_counts[proxy] = failures

            # Exponential backoff: 60s, 300s, 3600s (max 1 hour)
            if failures == 1:
                quarantine_seconds = base_quarantine_seconds
            elif failures == 2:
                quarantine_seconds = base_quarantine_seconds * 5
            else:
                quarantine_seconds = min(base_quarantine_seconds * 60, 3600)

            expire_time = time.monotonic() + quarantine_seconds
            self._quarantine[proxy] = expire_time
            logger.warning(
                "Proxy %s quarantined for %d seconds (failure #%d) due to session %s",
                proxy.server,
                quarantine_seconds,
                failures,
                session_id,
            )

    @property
    def active_session_count(self) -> int:
        """Number of active (non-expired) sticky sessions."""
        now = time.monotonic()
        return sum(1 for e in self._sessions.values() if now - e.created_at < e.ttl)

    def cleanup_expired_sessions(self) -> int:
        """Remove all expired sticky sessions. Returns count of removed sessions."""
        now = time.monotonic()
        expired = [sid for sid, entry in self._sessions.items() if now - entry.created_at >= entry.ttl]
        for sid in expired:
            del self._sessions[sid]
        if expired:
            logger.debug("Cleaned %d expired proxy sessions", len(expired))
        return len(expired)

    @classmethod
    def from_urls(cls, urls: list[str]) -> RoundRobinProxyPool:
        """Create pool from a list of proxy URL strings."""
        return cls([ProxyConfig.from_url(u) for u in urls])

    @classmethod
    def from_csv(cls, csv_urls: str) -> RoundRobinProxyPool | None:
        """Create pool from comma-separated proxy URL string.

        Returns None if the string is empty.
        """
        urls = [u.strip() for u in csv_urls.split(",") if u.strip()]
        if not urls:
            return None
        logger.info("Loaded %d proxies", len(urls))
        return cls.from_urls(urls)
