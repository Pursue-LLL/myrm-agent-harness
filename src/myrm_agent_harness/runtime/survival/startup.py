"""Startup performance monitoring toolkit.

[INPUT]

[OUTPUT]
- StartupTimer: Async context manager for phase/task timing (nested support)
- StartupMetrics: Structured metrics export (.to_dict()) with nested task timings

[POS]
Optional toolkit for monitoring application startup performance.
Provides standardized metrics collection and export for logging/monitoring systems.
Enhanced with nested task timing for granular profiling.
"""

from __future__ import annotations

import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

__all__ = ["StartupMetrics", "StartupTimer"]


@dataclass
class StartupMetrics:
    """Startup performance metrics (instance-level).

    Tracks elapsed time for each startup phase and nested tasks within phases.
    Follows framework design principle: provide .to_dict() for business layer export.
    """

    phase_timings: dict[str, float] = field(default_factory=dict)
    task_timings: dict[str, dict[str, float]] = field(default_factory=dict)
    _start_time: float = field(default_factory=time.perf_counter, init=False)

    def total_elapsed_ms(self) -> float:
        """Calculate total elapsed time since startup began (in milliseconds)."""
        return (time.perf_counter() - self._start_time) * 1000

    def to_dict(self) -> dict[str, Any]:
        """Export metrics for logging/monitoring.

        Returns:
            Dictionary with phase timings, nested task timings, and total elapsed time.
            Format: {
                "phases": {
                    "critical": {"total_ms": 150, "tasks": {"init_database": 10, ...}},
                    "core": {"total_ms": 50, "tasks": {...}},
                    ...
                },
                "total_elapsed_ms": 1234
            }
        """
        phases = {}
        for phase_name, phase_total in self.phase_timings.items():
            phases[phase_name] = {
                "total_ms": phase_total,
                "tasks": self.task_timings.get(phase_name, {}).copy(),
            }
        return {
            "phases": phases,
            "total_elapsed_ms": self.total_elapsed_ms(),
        }


class StartupTimer:
    """Optional startup performance tracker with nested task support.

    Provides async context manager for tracking startup phase timing and nested task timing.

    Example:
        ```python
        timer = StartupTimer()

        async with timer.phase("critical"):
            async with timer.task("init_database"):
                await init_database()
            async with timer.task("migrate_configs"):
                await migrate_configs()

        async with timer.phase("core"):
            async with timer.task("start_services"):
                await start_services()

        logger.info(f"Startup metrics: {timer.metrics.to_dict()}")
        # Output: {
        #   "phases": {
        #     "critical": {"total_ms": 150, "tasks": {"init_database": 10, "migrate_configs": 50, ...}},
        #     "core": {...}
        #   },
        #   "total_elapsed_ms": 1234
        # }
        ```

    Note:
        This is an optional tool. Applications can choose not to use it.
        Framework layer provides the tool, business layer decides when/how to use it.
    """

    def __init__(self) -> None:
        self.metrics = StartupMetrics()
        self._current_phase: str | None = None

    @asynccontextmanager
    async def phase(self, phase_name: str) -> AsyncGenerator[None]:
        """Track a startup phase timing.

        Args:
            phase_name: Name of the startup phase (e.g., "critical", "core", "warmup").

        Yields:
            None (context manager for timing scope).
        """
        phase_start = time.perf_counter()
        prev_phase = self._current_phase
        self._current_phase = phase_name

        if phase_name not in self.metrics.task_timings:
            self.metrics.task_timings[phase_name] = {}

        try:
            yield
        finally:
            elapsed_ms = (time.perf_counter() - phase_start) * 1000
            self.metrics.phase_timings[phase_name] = elapsed_ms
            self._current_phase = prev_phase

    @asynccontextmanager
    async def task(self, task_name: str) -> AsyncGenerator[None]:
        """Track a task timing within the current phase.

        Args:
            task_name: Name of the task (e.g., "init_database", "migrate_configs").

        Yields:
            None (context manager for timing scope).
        """
        if self._current_phase is None:
            raise RuntimeError("task() must be called within a phase() context")

        task_start = time.perf_counter()
        try:
            yield
        finally:
            elapsed_ms = (time.perf_counter() - task_start) * 1000
            self.metrics.task_timings[self._current_phase][task_name] = elapsed_ms
