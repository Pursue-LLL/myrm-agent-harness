"""Asynchronous loopback connectivity probe and proxy interception detector.

Executes low-overhead health probes against local endpoints (such as CLIProxyAPI,
Ollama, vLLM, or sandbox containers) to detect latency and proxy interception signatures.

[OUTPUT]
- LoopbackProbe: Async probe and proxy signature analyzer.

[INPUT]
- __future__
- asyncio
- time
- collections

[OUTPUT]
- LoopbackProbe

[POS]
Asynchronous loopback connectivity probe and proxy interception detector.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping

from myrm_agent_harness.core.network.loopback_types import (
    HealthStatus,
    LoopbackProbeResult,
)
from myrm_agent_harness.core.network.proxy_environment_guard import (
    ProxyEnvironmentGuard,
)

_INTERCEPTION_HEADER_SIGNATURES: tuple[str, ...] = (
    "x-surge-",
    "x-clash-",
    "proxy-agent",
    "via",
    "squid",
    "privoxy",
)


class LoopbackProbe:
    """Probes local loopback endpoints to verify reachable latency and detect proxy traps."""

    def __init__(self, timeout_seconds: float = 2.0) -> None:
        self.timeout_seconds: float = max(0.1, timeout_seconds)

    async def probe_tcp_port(
        self,
        host: str = "127.0.0.1",
        port: int = 8317,
        *,
        env: Mapping[str, str] | None = None,
    ) -> LoopbackProbeResult:
        """Probe loopback TCP reachability and check for proxy environment conflicts."""
        start_ts = time.perf_counter()
        snapshot = ProxyEnvironmentGuard.capture_snapshot(env)

        try:
            _reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=self.timeout_seconds,
            )
            latency_ms = (time.perf_counter() - start_ts) * 1000.0
            writer.close()
            await writer.wait_closed()

            return LoopbackProbeResult(
                target_host=host,
                target_port=port,
                status=HealthStatus.HEALTHY,
                is_reachable=True,
                latency_ms=round(latency_ms, 2),
            )

        except TimeoutError:
            latency_ms = (time.perf_counter() - start_ts) * 1000.0
            # If a proxy is configured and NO_PROXY doesn't cover loopback, timeout is likely a proxy dead-end
            intercepted = (
                snapshot.has_any_proxy_configured
                and not snapshot.covers_standard_loopback
            )
            return LoopbackProbeResult(
                target_host=host,
                target_port=port,
                status=(
                    HealthStatus.INTERCEPTED
                    if intercepted
                    else HealthStatus.UNREACHABLE
                ),
                is_reachable=False,
                latency_ms=round(latency_ms, 2),
                intercepted_by_proxy=intercepted,
                error_message=f"Connection timed out after {self.timeout_seconds}s",
            )

        except (ConnectionRefusedError, OSError) as exc:
            latency_ms = (time.perf_counter() - start_ts) * 1000.0
            intercepted = (
                snapshot.has_any_proxy_configured
                and not snapshot.covers_standard_loopback
            )
            return LoopbackProbeResult(
                target_host=host,
                target_port=port,
                status=(
                    HealthStatus.INTERCEPTED
                    if intercepted
                    else HealthStatus.UNREACHABLE
                ),
                is_reachable=False,
                latency_ms=round(latency_ms, 2),
                intercepted_by_proxy=intercepted,
                error_message=str(exc),
            )

    @staticmethod
    def detect_proxy_headers(headers: Mapping[str, str]) -> str | None:
        """Inspect HTTP response headers for external proxy interception fingerprints."""
        for key, val in headers.items():
            key_lower = key.lower()
            val_lower = val.lower()
            for sig in _INTERCEPTION_HEADER_SIGNATURES:
                if sig in key_lower or sig in val_lower:
                    return f"{key}: {val}"
        return None
