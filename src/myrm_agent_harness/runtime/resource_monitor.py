"""Resource monitor for single Agent instance.

Collects high-fidelity resource usage metrics for self-protection and observability:
- CPU usage
- Memory usage (RSS, VMS, Python GC, Native estimate)
- Disk usage
- Network I/O
- 512-point historical sampling
- On-demand heap profiling (tracemalloc)
- Production-visible [MEMORY] INFO logging (grep-friendly, 5-min interval + baseline/shutdown)

[INPUT]
- gc (POS: Python garbage collector)
- tracemalloc (POS: Python memory profiler)
- psutil (POS: System monitoring)

[OUTPUT]
- ResourceMetrics: Resource usage metrics.
- ResourceMonitor: Monitor resource usage with history and profiling.

[POS]
Resource monitor for single Agent instance. Provides high-fidelity observability
and historical data for the Server API and Control Plane.
"""

import asyncio
import contextlib
import gc
import logging
import threading
import time
import tracemalloc
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import psutil

logger = logging.getLogger(__name__)


@dataclass
class ResourceMetrics:
    """High-fidelity resource usage metrics."""

    cpu_percent: float
    memory_mb: float  # RSS
    vms_mb: float  # Virtual Memory Size
    python_gc_objects: int
    native_mb_estimate: float
    disk_mb: float
    network_sent_mb: float
    network_recv_mb: float
    timestamp: float

    def to_dict(self) -> dict[str, float | int]:
        return {
            "cpu_percent": self.cpu_percent,
            "memory_mb": self.memory_mb,
            "vms_mb": self.vms_mb,
            "python_gc_objects": self.python_gc_objects,
            "native_mb_estimate": self.native_mb_estimate,
            "disk_mb": self.disk_mb,
            "network_sent_mb": self.network_sent_mb,
            "network_recv_mb": self.network_recv_mb,
            "timestamp": self.timestamp,
        }


class ResourceMonitor:
    """Monitor resource usage for the current agent instance.

    Collects metrics periodically, maintains a 512-point history ring buffer,
    and provides on-demand heap profiling via tracemalloc.
    """

    def __init__(self, report_interval: float = 10.0, history_size: int = 512):
        """
        Initialize resource monitor.

        Args:
            report_interval: Interval between reports in seconds
            history_size: Number of historical data points to keep
        """
        self.report_interval = report_interval
        self.history_size = history_size

        self._monitor_task: asyncio.Task[None] | None = None
        self._process = psutil.Process()

        # History ring buffer
        self._history: deque[ResourceMetrics] = deque(maxlen=history_size)

        # Network baseline
        self._network_baseline = psutil.net_io_counters()

        # Profiling state
        self._is_profiling = False

        self._listeners: list[Callable[[ResourceMetrics], Awaitable[None]]] = []

        # INFO-level periodic logging (every _INFO_EVERY ticks = 5 minutes at 10s interval)
        self._info_every: int = max(1, int(300 / self.report_interval))
        self._tick_count: int = 0
        self._start_time: float = 0.0

    def add_listener(self, listener: Callable[[ResourceMetrics], Awaitable[None]]) -> None:
        """Add a listener to receive metrics updates."""
        if listener not in self._listeners:
            self._listeners.append(listener)

    def _log_memory_snapshot(self, prefix: str = "") -> None:
        """Emit a grep-friendly [MEMORY] INFO line for production observability."""
        try:
            mem = self._process.memory_info()
            rss_mb = int(mem.rss / (1024 * 1024))
            vms_mb = int(mem.vms / (1024 * 1024))
            cpu = self._process.cpu_percent(interval=0)
            threads = threading.active_count()
            uptime = int(time.monotonic() - self._start_time) if self._start_time else 0
            tag = f"{prefix} " if prefix else ""
            logger.info(
                "[MEMORY] %srss=%dmb vms=%dmb cpu=%.1f%% threads=%d uptime=%ds",
                tag,
                rss_mb,
                vms_mb,
                cpu,
                threads,
                uptime,
            )
        except Exception:
            pass

    async def start(self) -> None:
        """Start monitoring loop."""
        self._start_time = time.monotonic()
        logger.info(
            "Starting resource monitor (interval=%ss, history=%d)",
            self.report_interval,
            self.history_size,
        )
        self._log_memory_snapshot("baseline")
        self._monitor_task = asyncio.create_task(self._monitor_loop())

    async def _monitor_loop(self) -> None:
        """Background monitoring loop."""
        while True:
            try:
                await asyncio.sleep(self.report_interval)
                metrics = await self.collect_metrics()
                self._history.append(metrics)

                for listener in self._listeners:
                    try:
                        await listener(metrics)
                    except Exception as e:
                        logger.error("Error in resource monitor listener: %s", e)

                try:
                    from myrm_agent_harness.runtime.events import ResourceMetricsEvent, get_event_bus

                    get_event_bus().publish(ResourceMetricsEvent(metrics=metrics.to_dict(), history=self.get_history()))
                except Exception as e:
                    logger.debug("Failed to publish ResourceMetricsEvent: %s", e)

                self._tick_count += 1
                if self._tick_count % self._info_every == 0:
                    self._log_memory_snapshot()
                else:
                    logger.debug(
                        "Resource: CPU=%.1f%%, RSS=%.0fMB, Native~=%.0fMB, Objects=%d",
                        metrics.cpu_percent,
                        metrics.memory_mb,
                        metrics.native_mb_estimate,
                        metrics.python_gc_objects,
                    )

            except asyncio.CancelledError:
                logger.info("Resource monitor cancelled")
                break
            except Exception as e:
                logger.error("Error in monitor loop: %s", e)

    async def collect_metrics(self) -> ResourceMetrics:
        """
        Collect current resource usage metrics.

        Returns:
            ResourceMetrics instance
        """
        try:
            now = time.time()

            # CPU usage
            cpu_percent = self._process.cpu_percent(interval=0.1)

            # Memory usage
            memory_info = self._process.memory_info()
            rss_mb = memory_info.rss / (1024 * 1024)
            vms_mb = memory_info.vms / (1024 * 1024)

            # Python GC stats
            gc_objects = len(gc.get_objects())

            # Estimate Native Memory (RSS - Python Allocated)
            # This is a rough estimate. A typical Python object is ~100-200 bytes.
            # We use 150 bytes as an average for estimation.
            python_mb_estimate = (gc_objects * 150) / (1024 * 1024)
            native_mb_estimate = max(0.0, rss_mb - python_mb_estimate)

            # Disk usage
            disk_usage = psutil.disk_usage("/")
            disk_mb = disk_usage.used / (1024 * 1024)

            # Network I/O
            net_io = psutil.net_io_counters()
            network_sent_mb = (net_io.bytes_sent - self._network_baseline.bytes_sent) / (1024 * 1024)
            network_recv_mb = (net_io.bytes_recv - self._network_baseline.bytes_recv) / (1024 * 1024)

            return ResourceMetrics(
                cpu_percent=cpu_percent,
                memory_mb=rss_mb,
                vms_mb=vms_mb,
                python_gc_objects=gc_objects,
                native_mb_estimate=native_mb_estimate,
                disk_mb=disk_mb,
                network_sent_mb=network_sent_mb,
                network_recv_mb=network_recv_mb,
                timestamp=now,
            )

        except Exception as e:
            logger.error("Failed to collect metrics: %s", e)
            raise

    def get_history(self) -> list[dict[str, float | int]]:
        """Get the historical metrics as a list of dictionaries."""
        return [m.to_dict() for m in self._history]

    def start_profiling(self, frames: int = 10) -> bool:
        """Start heap profiling using tracemalloc.

        Args:
            frames: Number of frames to store in traceback

        Returns:
            bool: True if started successfully, False if already running
        """
        if self._is_profiling or tracemalloc.is_tracing():
            return False

        logger.warning("Starting heap profiling (tracemalloc). This may impact performance.")
        tracemalloc.start(frames)
        self._is_profiling = True
        return True

    def stop_profiling(self) -> list[dict[str, str | float | int]]:
        """Stop heap profiling and return the top 10 memory allocations.

        Returns:
            list: Top 10 memory allocations with file, line, and size
        """
        if not self._is_profiling or not tracemalloc.is_tracing():
            return []

        snapshot = tracemalloc.take_snapshot()
        tracemalloc.stop()
        self._is_profiling = False

        top_stats = snapshot.statistics("lineno")

        results = []
        for stat in top_stats[:10]:
            frame = stat.traceback[0]
            results.append(
                {
                    "file": frame.filename,
                    "line": frame.lineno,
                    "size_kb": stat.size / 1024,
                    "count": stat.count,
                }
            )

        logger.info("Stopped heap profiling. Captured %d top allocations.", len(results))
        return results

    async def stop(self) -> None:
        """Stop monitoring loop."""
        self._log_memory_snapshot("shutdown")

        if self._monitor_task:
            self._monitor_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._monitor_task

        if self._is_profiling:
            tracemalloc.stop()
            self._is_profiling = False

        logger.info("Resource monitor stopped")


# Global singleton instance
_monitor_instance: ResourceMonitor | None = None


def get_resource_monitor() -> ResourceMonitor:
    """Get or create the global resource monitor instance."""
    global _monitor_instance
    if _monitor_instance is None:
        _monitor_instance = ResourceMonitor()
    return _monitor_instance
