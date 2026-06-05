"""Global memory pressure monitor with multi-level degradation support.

Detects system memory pressure and notifies subscribers for coordinated response.
Supports cgroup v2 memory limits (container-aware) with psutil fallback.

[INPUT]
- asyncio (POS: Python async runtime)
- gc (POS: Python garbage collector)
- psutil (POS: System monitoring, optional)
- /sys/fs/cgroup/memory.current + memory.max (POS: cgroup v2 memory files)

[OUTPUT]
- PressureLevel: 4-level pressure enum (NORMAL/WARNING/CRITICAL/EMERGENCY)
- PressureConfig: Threshold and behavior configuration
- PressureEvent: Pressure level change event with direction
- PressureSubscriber: Protocol for pressure-aware components
- MemoryPressureMonitor: Core monitor with Pub/Sub + Pull dual mode
- init_memory_pressure_monitor(): Module-level singleton initializer
- get_memory_pressure_monitor(): Module-level singleton accessor

[POS]
Global memory pressure coordination. Framework provides the monitor and hooks;
business layer registers subscribers to decide degradation strategies.
Follows the framework's three responsibilities: resource management,
performance optimization, self-protection.
"""

from __future__ import annotations

import asyncio
import contextlib
import gc
import logging
import time
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Protocol, runtime_checkable

try:
    import psutil
except (ImportError, TypeError):
    psutil = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

_CGROUP_MEMORY_CURRENT = Path("/sys/fs/cgroup/memory.current")
_CGROUP_MEMORY_MAX = Path("/sys/fs/cgroup/memory.max")


class PressureLevel(IntEnum):
    """Memory pressure levels, ordered by severity."""

    NORMAL = 0
    WARNING = 1
    CRITICAL = 2
    EMERGENCY = 3


@dataclass(frozen=True, slots=True)
class PressureConfig:
    """Memory pressure thresholds and monitor behavior.

    All thresholds are system memory usage percentages.
    Escalation/de-escalation counts implement hysteresis to avoid flapping.
    """

    warning_threshold: float = 80.0
    critical_threshold: float = 90.0
    emergency_threshold: float = 95.0
    check_interval_seconds: float = 5.0
    escalation_count: int = 2
    de_escalation_count: int = 3
    subscriber_timeout_seconds: float = 5.0

    def __post_init__(self) -> None:
        for name, val in [
            ("warning_threshold", self.warning_threshold),
            ("critical_threshold", self.critical_threshold),
            ("emergency_threshold", self.emergency_threshold),
        ]:
            if not 50.0 <= val <= 99.0:
                raise ValueError(f"{name} must be in [50, 99], got {val}")
        if not self.warning_threshold < self.critical_threshold < self.emergency_threshold:
            raise ValueError(
                f"Thresholds must be strictly increasing: "
                f"{self.warning_threshold} < {self.critical_threshold} < {self.emergency_threshold}"
            )
        if self.check_interval_seconds <= 0:
            raise ValueError(f"check_interval_seconds must be > 0, got {self.check_interval_seconds}")
        if self.escalation_count < 1:
            raise ValueError(f"escalation_count must be >= 1, got {self.escalation_count}")
        if self.de_escalation_count < 1:
            raise ValueError(f"de_escalation_count must be >= 1, got {self.de_escalation_count}")
        if self.subscriber_timeout_seconds <= 0:
            raise ValueError(f"subscriber_timeout_seconds must be > 0, got {self.subscriber_timeout_seconds}")


@dataclass(frozen=True, slots=True)
class PressureEvent:
    """Memory pressure level change event."""

    level: PressureLevel
    previous_level: PressureLevel
    memory_percent: float
    timestamp: float

    @property
    def escalated(self) -> bool:
        return self.level > self.previous_level

    @property
    def de_escalated(self) -> bool:
        return self.level < self.previous_level


@runtime_checkable
class PressureSubscriber(Protocol):
    """Protocol for components that respond to memory pressure changes."""

    async def on_pressure_change(self, event: PressureEvent) -> None: ...


# Alias for clarity in shedding scenarios
MemoryShedder = PressureSubscriber


def _read_cgroup_memory_percent() -> float | None:
    """Read memory usage from cgroup v2. Returns None if unavailable."""
    try:
        current_text = _CGROUP_MEMORY_CURRENT.read_text().strip()
        max_text = _CGROUP_MEMORY_MAX.read_text().strip()
        if max_text == "max":
            return None
        current = int(current_text)
        maximum = int(max_text)
        if maximum <= 0:
            return None
        return (current / maximum) * 100.0
    except (FileNotFoundError, ValueError, OSError):
        return None


def _read_psutil_memory_percent() -> float:
    """Read system memory usage via psutil."""
    if psutil is None:
        return 0.0
    return psutil.virtual_memory().percent


class MemoryPressureMonitor:
    """Global memory pressure monitor.

    Periodically checks system memory usage and notifies subscribers
    when pressure level changes. Uses cgroup v2 in containers with
    psutil fallback for bare-metal/desktop.

    Dual access modes:
    - Pub/Sub: Register subscribers for active notifications on level changes
    - Pull: Query current_level / current_memory_percent at any time
    """

    def __init__(self, config: PressureConfig | None = None) -> None:
        self._config = config or PressureConfig()
        self._level = PressureLevel.NORMAL
        self._memory_percent = 0.0
        self._subscribers: list[PressureSubscriber] = []
        self._monitor_task: asyncio.Task[None] | None = None

        self._consecutive_at_target = 0
        self._consecutive_below = 0
        self._use_cgroup = _CGROUP_MEMORY_CURRENT.exists() and _CGROUP_MEMORY_MAX.exists()

    async def start(self) -> None:
        """Start the background monitoring loop."""
        if self._monitor_task is not None:
            return
        self._memory_percent = self._read_memory_percent()
        self._level = self._classify_level(self._memory_percent)
        source = "cgroup v2" if self._use_cgroup else "psutil"
        logger.info(
            "Memory pressure monitor starting (source=%s, interval=%.1fs, initial=%.1f%% %s)",
            source,
            self._config.check_interval_seconds,
            self._memory_percent,
            self._level.name,
        )
        self._monitor_task = asyncio.create_task(self._monitor_loop())

    async def stop(self) -> None:
        """Stop the monitoring loop."""
        if self._monitor_task is None:
            return
        self._monitor_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._monitor_task
        self._monitor_task = None
        logger.info("Memory pressure monitor stopped")

    def subscribe(self, subscriber: PressureSubscriber) -> None:
        """Register a subscriber for pressure change notifications."""
        if subscriber not in self._subscribers:
            self._subscribers.append(subscriber)

    def unsubscribe(self, subscriber: PressureSubscriber) -> None:
        """Remove a subscriber."""
        with contextlib.suppress(ValueError):
            self._subscribers.remove(subscriber)

    @property
    def current_level(self) -> PressureLevel:
        """Current pressure level (Pull mode)."""
        return self._level

    @property
    def current_memory_percent(self) -> float:
        """Last observed memory usage percentage."""
        return self._memory_percent

    def is_under_pressure(self) -> bool:
        """Quick check: is memory pressure above NORMAL?"""
        return self._level > PressureLevel.NORMAL

    def _read_memory_percent(self) -> float:
        """Read current memory usage, preferring cgroup v2 in containers."""
        if self._use_cgroup:
            cgroup_pct = _read_cgroup_memory_percent()
            if cgroup_pct is not None:
                return cgroup_pct
        return _read_psutil_memory_percent()

    def _classify_level(self, percent: float) -> PressureLevel:
        """Map memory percentage to pressure level."""
        cfg = self._config
        if percent >= cfg.emergency_threshold:
            return PressureLevel.EMERGENCY
        if percent >= cfg.critical_threshold:
            return PressureLevel.CRITICAL
        if percent >= cfg.warning_threshold:
            return PressureLevel.WARNING
        return PressureLevel.NORMAL

    async def _monitor_loop(self) -> None:
        """Background loop: check memory → apply hysteresis → notify."""
        while True:
            try:
                await asyncio.sleep(self._config.check_interval_seconds)
                self._memory_percent = self._read_memory_percent()
                sampled_level = self._classify_level(self._memory_percent)

                new_level = self._apply_hysteresis(sampled_level)
                if new_level != self._level:
                    previous = self._level
                    self._level = new_level
                    event = PressureEvent(
                        level=new_level,
                        previous_level=previous,
                        memory_percent=self._memory_percent,
                        timestamp=time.monotonic(),
                    )
                    direction = "ESCALATED" if event.escalated else "DE-ESCALATED"
                    logger.warning(
                        "Memory pressure %s: %s -> %s (%.1f%%)",
                        direction,
                        previous.name,
                        new_level.name,
                        self._memory_percent,
                    )
                    if new_level == PressureLevel.EMERGENCY:
                        await self._emergency_gc()
                    await self._notify_subscribers(event)

            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error in memory pressure monitor loop")

    def _apply_hysteresis(self, sampled: PressureLevel) -> PressureLevel:
        """Apply hysteresis to prevent flapping between levels.

        Escalation requires `escalation_count` consecutive samples at higher level.
        De-escalation requires `de_escalation_count` consecutive samples at lower level.
        """
        if sampled > self._level:
            self._consecutive_at_target += 1
            self._consecutive_below = 0
            if self._consecutive_at_target >= self._config.escalation_count:
                self._consecutive_at_target = 0
                return sampled
        elif sampled < self._level:
            self._consecutive_below += 1
            self._consecutive_at_target = 0
            if self._consecutive_below >= self._config.de_escalation_count:
                self._consecutive_below = 0
                return sampled
        else:
            self._consecutive_at_target = 0
            self._consecutive_below = 0

        return self._level

    async def _notify_subscribers(self, event: PressureEvent) -> None:
        """Notify all subscribers with per-subscriber exception isolation."""
        for subscriber in list(self._subscribers):
            try:
                await asyncio.wait_for(
                    subscriber.on_pressure_change(event),
                    timeout=self._config.subscriber_timeout_seconds,
                )
            except TimeoutError:
                logger.warning(
                    "Subscriber %s timed out (%.1fs) on pressure change %s",
                    type(subscriber).__name__,
                    self._config.subscriber_timeout_seconds,
                    event.level.name,
                )
            except Exception:
                logger.exception(
                    "Subscriber %s failed on pressure change %s",
                    type(subscriber).__name__,
                    event.level.name,
                )

    async def _emergency_gc(self) -> None:
        """Run garbage collection in thread pool to avoid blocking event loop."""
        try:
            collected = await asyncio.to_thread(gc.collect)
            logger.warning("Emergency GC collected %d objects", collected)
        except Exception:
            logger.exception("Emergency GC failed")


_monitor: MemoryPressureMonitor | None = None


def init_memory_pressure_monitor(config: PressureConfig | None = None) -> MemoryPressureMonitor:
    """Initialize the module-level singleton monitor.

    Safe to call multiple times; returns existing instance if already initialized.
    """
    global _monitor
    if _monitor is None:
        _monitor = MemoryPressureMonitor(config)
    return _monitor


def get_memory_pressure_monitor() -> MemoryPressureMonitor | None:
    """Get the module-level singleton monitor, or None if not initialized."""
    return _monitor
