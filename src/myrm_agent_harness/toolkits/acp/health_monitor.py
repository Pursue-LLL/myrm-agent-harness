"""Health monitor for RuntimeBackend instances.

Periodically checks backend liveness, applies backoff + ``close()`` on dead
backends (so the next ``run_turn`` can reconnect), enforces a restart budget,
and publishes health events via EventBus.

[INPUT]
- (none)

[OUTPUT]
- HealthMetrics: Health metrics for a single backend.
- HealthMonitor: Monitors RuntimeBackend health and clears stale handles a...

[POS]
Health monitor for RuntimeBackend instances.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from dataclasses import dataclass, field

from myrm_agent_harness.toolkits.acp.event_bus import EventBus
from myrm_agent_harness.toolkits.acp.types import (
    RuntimeBackend,
    RuntimeEventType,
    create_event,
)

logger = logging.getLogger(__name__)

_DEFAULT_CHECK_INTERVAL = 30.0
_DEFAULT_MAX_RESTARTS = 5
_BASE_BACKOFF = 2.0


@dataclass
class HealthMetrics:
    """Health metrics for a single backend."""

    restart_count: int = 0
    last_crash_time: float | None = None
    last_check_time: float | None = None
    total_uptime_seconds: float = 0.0
    _start_time: float | None = field(default=None, init=False, repr=False)

    def record_start(self) -> None:
        self._start_time = time.monotonic()

    def record_crash(self) -> None:
        self.restart_count += 1
        self.last_crash_time = time.time()
        if self._start_time is not None:
            self.total_uptime_seconds += time.monotonic() - self._start_time
            self._start_time = None

    def to_dict(self) -> dict[str, object]:
        return {
            "restart_count": self.restart_count,
            "last_crash_time": self.last_crash_time,
            "last_check_time": self.last_check_time,
            "total_uptime_seconds": round(self.total_uptime_seconds, 2),
        }


class HealthMonitor:
    """Monitors RuntimeBackend health and clears stale handles after crashes.

    Usage::

        monitor = HealthMonitor(event_bus=bus)
        monitor.register(backend)
        await monitor.start()
        # ... later ...
        await monitor.stop()
    """

    def __init__(
        self,
        event_bus: EventBus | None = None,
        *,
        check_interval: float = _DEFAULT_CHECK_INTERVAL,
        max_restarts: int = _DEFAULT_MAX_RESTARTS,
    ) -> None:
        self._event_bus = event_bus
        self._check_interval = check_interval
        self._max_restarts = max_restarts
        self._backends: dict[str, RuntimeBackend] = {}
        self._metrics: dict[str, HealthMetrics] = {}
        self._task: asyncio.Task[None] | None = None

    def register(self, backend: RuntimeBackend) -> None:
        """Register a backend for health monitoring."""
        self._backends[backend.name] = backend
        self._metrics[backend.name] = HealthMetrics()

    def unregister(self, name: str) -> None:
        """Remove a backend from monitoring."""
        self._backends.pop(name, None)
        self._metrics.pop(name, None)

    def get_metrics(self, name: str) -> HealthMetrics | None:
        """Get health metrics for a backend."""
        return self._metrics.get(name)

    def get_all_metrics(self) -> dict[str, dict[str, object]]:
        """Get health metrics for all monitored backends."""
        return {name: m.to_dict() for name, m in self._metrics.items()}

    async def start(self) -> None:
        """Start the periodic health check loop."""
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._check_loop())
        logger.info("health_monitor_started interval=%.1fs", self._check_interval)

    async def stop(self) -> None:
        """Stop the health check loop."""
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
            logger.info("health_monitor_stopped")

    async def _check_loop(self) -> None:
        while True:
            for name, backend in list(self._backends.items()):
                metrics = self._metrics.get(name)
                if metrics is None:
                    continue

                metrics.last_check_time = time.time()

                try:
                    alive = backend.is_alive
                except Exception:
                    logger.warning("health_check_error name=%s", name, exc_info=True)
                    alive = False

                if not alive:
                    await self._handle_crash(name, backend, metrics)
                elif metrics._start_time is None:
                    metrics.record_start()

            await asyncio.sleep(self._check_interval)

    async def _handle_crash(
        self,
        name: str,
        backend: RuntimeBackend,
        metrics: HealthMetrics,
    ) -> None:
        """Handle a non-alive backend: emit telemetry, respect restart budget, close handle.

        Actual process respawn happens on the next ``run_turn`` for lazy backends
        (e.g. ``AcpRuntime``); this loop only clears stale state after backoff.
        """
        metrics.record_crash()

        if self._event_bus is not None:
            await self._event_bus.emit(
                create_event(
                    RuntimeEventType.STATUS_UPDATE,
                    session_id=f"{name}-health",
                    status="crashed",
                    message=f"Backend '{name}' crashed (restart #{metrics.restart_count})",
                )
            )

        if metrics.restart_count > self._max_restarts:
            logger.error(
                "health_max_restarts_exceeded name=%s count=%d max=%d",
                name,
                metrics.restart_count,
                self._max_restarts,
            )
            if self._event_bus is not None:
                await self._event_bus.emit(
                    create_event(
                        RuntimeEventType.ERROR,
                        session_id=f"{name}-health",
                        error={
                            "code": "process_crashed",
                            "message": f"Backend '{name}' exceeded max restarts ({self._max_restarts})",
                            "retryable": False,
                        },
                    )
                )
            return

        backoff = _BASE_BACKOFF ** min(metrics.restart_count, 6)
        logger.warning(
            "health_backend_crashed name=%s attempt=%d backoff=%.1fs",
            name,
            metrics.restart_count,
            backoff,
        )
        await asyncio.sleep(backoff)

        try:
            await backend.close()
        except Exception:
            logger.debug("health_close_after_crash_failed name=%s", name, exc_info=True)
