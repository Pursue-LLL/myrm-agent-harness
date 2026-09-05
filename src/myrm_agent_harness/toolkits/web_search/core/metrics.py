"""In-process counters for web search operations (thread-safe, optional observability hook).

[INPUT]
- (none)

[OUTPUT]
- WebSearchMetrics: Thread-safe counters suitable for logging or periodic exp...

[POS]
In-process counters for web search operations (thread-safe, optional observability hook).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field


@dataclass
class WebSearchMetrics:
    """Thread-safe counters suitable for logging or periodic export."""

    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)
    search_attempts: int = 0
    search_successes: int = 0
    search_terminal_failures: int = 0
    search_retry_scheduled: int = 0
    reranker_degraded_count: int = 0
    fallback_triggered_count: int = 0
    fallback_successes: int = 0
    fallback_failures: int = 0
    chain_hop_count: int = 0
    provider_attempts: dict[str, int] = field(default_factory=dict)
    provider_successes: dict[str, int] = field(default_factory=dict)
    provider_quota_exceeded: dict[str, int] = field(default_factory=dict)

    def record_attempt(self) -> None:
        with self._lock:
            self.search_attempts += 1

    def record_success(self) -> None:
        with self._lock:
            self.search_successes += 1

    def record_terminal_failure(self) -> None:
        with self._lock:
            self.search_terminal_failures += 1

    def record_retry_scheduled(self) -> None:
        with self._lock:
            self.search_retry_scheduled += 1

    def record_reranker_degraded(self) -> None:
        """Record reranker degradation event (for monitoring alerts)"""
        with self._lock:
            self.reranker_degraded_count += 1

    def record_fallback_triggered(self) -> None:
        """Record fallback triggered (primary service non-retryable error)"""
        with self._lock:
            self.fallback_triggered_count += 1

    def record_fallback_success(self) -> None:
        """Record fallback success"""
        with self._lock:
            self.fallback_successes += 1

    def record_fallback_failure(self) -> None:
        """Record fallback failure"""
        with self._lock:
            self.fallback_failures += 1

    def record_chain_hop(self, *, from_provider: str, to_provider: str) -> None:
        """Record failover hop between providers in a priority chain."""
        _ = (from_provider, to_provider)
        with self._lock:
            self.chain_hop_count += 1

    def record_provider_search(
        self,
        provider: str,
        *,
        success: bool,
        quota_exceeded: bool = False,
    ) -> None:
        """Record provider-specific search attempt and outcome."""
        with self._lock:
            self.provider_attempts[provider] = self.provider_attempts.get(provider, 0) + 1
            if success:
                self.provider_successes[provider] = self.provider_successes.get(provider, 0) + 1
            if quota_exceeded:
                self.provider_quota_exceeded[provider] = self.provider_quota_exceeded.get(provider, 0) + 1

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "search_attempts": self.search_attempts,
                "search_successes": self.search_successes,
                "search_terminal_failures": self.search_terminal_failures,
                "search_retry_scheduled": self.search_retry_scheduled,
                "reranker_degraded_count": self.reranker_degraded_count,
                "fallback_triggered_count": self.fallback_triggered_count,
                "fallback_successes": self.fallback_successes,
                "fallback_failures": self.fallback_failures,
                "chain_hop_count": self.chain_hop_count,
                "provider_attempts": dict(self.provider_attempts),
                "provider_successes": dict(self.provider_successes),
                "provider_quota_exceeded": dict(self.provider_quota_exceeded),
            }


web_search_metrics = WebSearchMetrics()
