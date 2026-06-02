"""Global adaptive maintenance scheduler.

Central coordinator that decides when/whether background tasks may run,
based on real-time system load, per-agent health scores, and memory pressure.

Design principles:
- Non-blocking: `request_capacity()` returns immediately
- Preempt-safe: Busy-system denial includes retry-after hint
- Deployment-agnostic: Works with any LoadSensor implementation
- Prompt-cache-safe: Never modifies message content or order
- Memory-pressure-aware: Subscribes to MemoryPressureMonitor for coordinated response

[INPUT]
- runtime.memory_pressure::PressureEvent, PressureLevel, PressureSubscriber (POS: Global memory pressure coordination. Framework provides the monitor and hooks; business layer registers subscribers to decide degradation strategies. Follows the framework's three responsibilities: resource management, performance optimization, self-protection.)

[OUTPUT]
- GlobalAdaptiveScheduler: Adaptive scheduler that throttles maintenance based on sy...
- init_maintenance_scheduler: Initialize the module-level singleton scheduler.
- get_maintenance_scheduler: Get the module-level singleton scheduler, or None if not ...

[POS]
Global adaptive maintenance scheduler.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field

from myrm_agent_harness.runtime.memory_pressure import (
    PressureEvent,
    PressureLevel,
    PressureSubscriber,
)

from .protocols import (
    AgentHealthScore,
    CapacityDenial,
    CapacityTicket,
    LoadSensor,
    MaintenanceScheduler,
    MaintenanceTaskType,
    SystemLoadLevel,
    SystemLoadSnapshot,
)

logger = logging.getLogger(__name__)

_RETRY_SECONDS: dict[SystemLoadLevel, float] = {
    SystemLoadLevel.IDLE: 0.0,
    SystemLoadLevel.NORMAL: 10.0,
    SystemLoadLevel.BUSY: 30.0,
    SystemLoadLevel.OVERLOADED: 60.0,
}

_CONCURRENT_LIMITS: dict[SystemLoadLevel, int] = {
    SystemLoadLevel.IDLE: 4,
    SystemLoadLevel.NORMAL: 2,
    SystemLoadLevel.BUSY: 1,
    SystemLoadLevel.OVERLOADED: 0,
}


@dataclass
class _ActiveTicket:
    """Internal tracking for an issued ticket."""

    ticket: CapacityTicket
    issued_at: float = field(default_factory=time.monotonic)


class GlobalAdaptiveScheduler(MaintenanceScheduler, PressureSubscriber):
    """Adaptive scheduler that throttles maintenance based on system load.

    Features:
    - Dynamic concurrency limits per load level (IDLE=4, NORMAL=2, BUSY=1, OVERLOADED=0)
    - Health-score urgency override: critical agents (score < 30) bypass BUSY limits
    - Stale ticket auto-expiry (default 300s) prevents resource leaks
    - MemoryPressureMonitor integration: auto-blocks at CRITICAL/EMERGENCY pressure
    - Thread-safe via asyncio.Lock
    """

    def __init__(
        self,
        sensor: LoadSensor,
        *,
        ticket_ttl_seconds: float = 300.0,
    ) -> None:
        self._sensor = sensor
        self._ticket_ttl = ticket_ttl_seconds
        self._active: dict[str, _ActiveTicket] = {}
        self._lock = asyncio.Lock()
        self._last_snapshot: SystemLoadSnapshot | None = None
        self._memory_pressure_level = PressureLevel.NORMAL

        # Autonomous Budget & Circuit Breaker state
        self._daily_budget: float = 0.0  # 0 means unlimited
        self._current_spend: float = 0.0
        self._consecutive_failures: dict[MaintenanceTaskType, int] = {}
        self._backoff_until: dict[MaintenanceTaskType, float] = {}

    def configure_budget(self, daily_budget: float) -> None:
        """Set the daily token/cost budget for autonomous maintenance tasks."""
        self._daily_budget = daily_budget
        self._current_spend = 0.0
        logger.info(f"Maintenance budget configured: ${daily_budget}/day")

    def report_outcome(self, task_type: MaintenanceTaskType, success: bool, cost: float = 0.0) -> None:
        """Report the outcome and cost of a maintenance task to adjust backoff and budget."""
        self._current_spend += cost
        if success:
            self._consecutive_failures[task_type] = 0
            self._backoff_until[task_type] = 0.0
        else:
            fails = self._consecutive_failures.get(task_type, 0) + 1
            self._consecutive_failures[task_type] = fails
            # Exponential backoff: 2^fails * 30 seconds (max 1 hour)
            backoff_seconds = min(3600.0, (2**fails) * 30.0)
            self._backoff_until[task_type] = time.monotonic() + backoff_seconds
            logger.warning(
                f"Task {task_type.name} failed {fails} consecutive times. "
                f"Circuit breaker triggered: backing off for {backoff_seconds}s. Total spend: ${self._current_spend}"
            )

    async def on_pressure_change(self, event: PressureEvent) -> None:
        """PressureSubscriber callback: adjust scheduling based on memory pressure."""
        self._memory_pressure_level = event.level
        if event.escalated and event.level >= PressureLevel.CRITICAL:
            logger.warning(
                "Memory pressure %s: blocking all maintenance tasks",
                event.level.name,
            )
        elif event.de_escalated and event.level < PressureLevel.CRITICAL:
            logger.info(
                "Memory pressure dropped to %s: maintenance tasks unblocked",
                event.level.name,
            )

    async def request_capacity(
        self,
        task_type: MaintenanceTaskType,
        health_score: AgentHealthScore | None = None,
    ) -> CapacityTicket | CapacityDenial:
        async with self._lock:
            # 1. Check Circuit Breaker / Exponential Backoff
            backoff = self._backoff_until.get(task_type, 0.0)
            now = time.monotonic()
            if now < backoff:
                return CapacityDenial(
                    reason=f"Task {task_type.name} in exponential backoff circuit breaker",
                    retry_after_seconds=backoff - now,
                )

            # 2. Check Budget Lock
            if self._daily_budget > 0 and self._current_spend >= self._daily_budget:
                return CapacityDenial(
                    reason=f"Daily maintenance budget (${self._daily_budget}) exhausted (Current spend: ${self._current_spend})",
                    retry_after_seconds=3600.0,
                )

            # 3. Check Memory Pressure
            if self._memory_pressure_level >= PressureLevel.CRITICAL:
                return CapacityDenial(
                    reason=f"Memory pressure {self._memory_pressure_level.name}: all maintenance blocked",
                    retry_after_seconds=30.0,
                )

            self._expire_stale_tickets()
            snapshot = self._sensor.read()
            self._last_snapshot = snapshot

            max_concurrent = _CONCURRENT_LIMITS[snapshot.level]

            if health_score and health_score.score < 30 and snapshot.level == SystemLoadLevel.BUSY:
                max_concurrent = max(max_concurrent, 1)
                logger.info(
                    "Urgency override: health_score=%d allows 1 task despite BUSY load",
                    health_score.score,
                )

            if len(self._active) >= max_concurrent:
                retry = _RETRY_SECONDS[snapshot.level]
                logger.debug(
                    "Capacity denied: active=%d limit=%d load=%s retry_after=%.0fs",
                    len(self._active),
                    max_concurrent,
                    snapshot.level.name,
                    retry,
                )
                return CapacityDenial(
                    reason=f"System load {snapshot.level.name}: {len(self._active)}/{max_concurrent} slots used",
                    retry_after_seconds=retry,
                    load_snapshot=snapshot,
                )

            ticket = CapacityTicket(
                ticket_id=f"mt_{uuid.uuid4().hex[:12]}",
                task_type=task_type,
            )
            self._active[ticket.ticket_id] = _ActiveTicket(ticket=ticket)

            logger.debug(
                "Capacity granted: ticket=%s task=%s active=%d/%d load=%s",
                ticket.ticket_id,
                task_type.name,
                len(self._active),
                max_concurrent,
                snapshot.level.name,
            )
            return ticket

    async def release_capacity(self, ticket: CapacityTicket) -> None:
        async with self._lock:
            removed = self._active.pop(ticket.ticket_id, None)
            if removed:
                duration = time.monotonic() - removed.issued_at
                logger.debug(
                    "Ticket released: %s (held %.1fs)",
                    ticket.ticket_id,
                    duration,
                )

    def is_idle(self) -> bool:
        if self._last_snapshot is None:
            snapshot = self._sensor.read()
            self._last_snapshot = snapshot
        return self._last_snapshot.level == SystemLoadLevel.IDLE and len(self._active) == 0

    @property
    def active_count(self) -> int:
        return len(self._active)

    @property
    def last_snapshot(self) -> SystemLoadSnapshot | None:
        return self._last_snapshot

    def _expire_stale_tickets(self) -> None:
        now = time.monotonic()
        expired = [tid for tid, at in self._active.items() if (now - at.issued_at) > self._ticket_ttl]
        for tid in expired:
            self._active.pop(tid, None)
            logger.warning("Stale ticket expired: %s (TTL=%.0fs)", tid, self._ticket_ttl)


_scheduler: GlobalAdaptiveScheduler | None = None


def init_maintenance_scheduler(
    sensor: LoadSensor,
    *,
    ticket_ttl_seconds: float = 300.0,
) -> GlobalAdaptiveScheduler:
    """Initialize the module-level singleton scheduler.

    Automatically subscribes to the global MemoryPressureMonitor if available.
    Safe to call multiple times; returns existing instance if already initialized.
    """
    global _scheduler
    if _scheduler is None:
        _scheduler = GlobalAdaptiveScheduler(sensor, ticket_ttl_seconds=ticket_ttl_seconds)

        from myrm_agent_harness.runtime.memory_pressure import get_memory_pressure_monitor

        monitor = get_memory_pressure_monitor()
        if monitor is not None:
            monitor.subscribe(_scheduler)
            logger.info(
                "Maintenance scheduler initialized with sensor=%s, subscribed to MemoryPressureMonitor",
                type(sensor).__name__,
            )
        else:
            logger.info("Maintenance scheduler initialized with sensor=%s", type(sensor).__name__)
    return _scheduler


def get_maintenance_scheduler() -> GlobalAdaptiveScheduler | None:
    """Get the module-level singleton scheduler, or None if not initialized."""
    return _scheduler
