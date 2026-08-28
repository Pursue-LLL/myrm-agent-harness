"""HTTP/3 (QUIC) egress probe and L1 retry metrics.

[INPUT]
- scrapling.fetchers::AsyncFetcher (POS: Scrapling static HTTP fetcher, used only for QUIC probe)

[OUTPUT]
- is_http3_retry_enabled: env gate for MYRM_HTTP3_RETRY
- is_quic_egress_available: lazy one-shot QUIC egress probe
- record_http3_retry / get_http3_retry_metrics: L1 retry counters

[POS]
Process-level QUIC availability gate and observability for HttpFetcher L1-QUIC-Retry lane.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_PROBE_URL = "https://cloudflare-quic.com/"
_PROBE_TIMEOUT_SECONDS = 5.0

_probe_lock = asyncio.Lock()
_quic_available: bool | None = None
_metrics_lock = threading.Lock()


@dataclass
class Http3RetryMetrics:
    attempts: int = 0
    success: int = 0

    def record(self, *, succeeded: bool) -> None:
        self.attempts += 1
        if succeeded:
            self.success += 1

    def to_dict(self) -> dict[str, int]:
        return {
            "http3_retry_attempts": self.attempts,
            "http3_retry_success": self.success,
        }


_metrics = Http3RetryMetrics()


def is_http3_retry_enabled() -> bool:
    """Whether L1 HTTP/3 retry lane is enabled via env."""
    return os.getenv("MYRM_HTTP3_RETRY", "0").lower() in ("true", "1", "yes")


async def is_quic_egress_available() -> bool:
    """Lazy one-shot QUIC egress probe; cached for process lifetime."""
    global _quic_available

    if not is_http3_retry_enabled():
        return False

    if _quic_available is not None:
        return _quic_available

    async with _probe_lock:
        if _quic_available is not None:
            return _quic_available

        _quic_available = await _probe_quic_egress()
        if _quic_available:
            logger.info("QUIC egress probe succeeded; HTTP/3 L1 retry is available")
        else:
            logger.warning("QUIC egress probe failed; HTTP/3 L1 retry disabled for this process")
        return _quic_available


async def _probe_quic_egress() -> bool:
    try:
        from scrapling.fetchers import AsyncFetcher  # type: ignore[import-untyped]

        response = await AsyncFetcher.get(
            _PROBE_URL,
            http3=True,
            impersonate=None,
            timeout=int(_PROBE_TIMEOUT_SECONDS),
            retries=0,
        )
        return response.status < 500
    except Exception as exc:
        logger.debug("QUIC egress probe error: %s", exc)
        return False


def record_http3_retry(*, succeeded: bool) -> None:
    with _metrics_lock:
        _metrics.record(succeeded=succeeded)


def get_http3_retry_metrics() -> dict[str, int]:
    with _metrics_lock:
        return _metrics.to_dict()


def reset_http3_state_for_tests() -> None:
    """Reset probe cache and metrics (tests only)."""
    global _quic_available
    _quic_available = None
    with _metrics_lock:
        _metrics.attempts = 0
        _metrics.success = 0
