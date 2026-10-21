"""Host physical resource watermark monitor and overload detector (Item 60).

[INPUT]
- System resource probes (CPU, memory, active worker counter) or injected sampler.
- Configurable thresholds (cpu_threshold_percent, memory_threshold_percent, max_local_workers).

[OUTPUT]
- Real-time ResourceWatermark snapshots and offload recommendations.
- Peak usage statistics across a swarm dispatch session.

[POS]
- Resource governance layer for Item 60 laptop resource protection.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from .types import ExecutionTarget, ResourceWatermark

logger = logging.getLogger(__name__)

# Type alias for external resource probe: returns tuple (cpu_percent, memory_percent)
ResourceSampler = Callable[[], tuple[float, float]]


class ResourceWatermarkMonitor:
    """Monitors host machine CPU and Memory to prevent physical resource saturation."""

    def __init__(
        self,
        cpu_threshold_percent: float = 80.0,
        memory_threshold_percent: float = 80.0,
        max_recommended_local_workers: int = 4,
        custom_sampler: ResourceSampler | None = None,
    ) -> None:
        self.cpu_threshold = cpu_threshold_percent
        self.memory_threshold = memory_threshold_percent
        self.max_local_workers = max_recommended_local_workers
        self._sampler = custom_sampler or self._default_probe
        self._active_local_count = 0
        self._peak_cpu = 0.0
        self._peak_memory = 0.0

    def _default_probe(self) -> tuple[float, float]:
        """Default probe using psutil if available, otherwise gentle mock."""
        try:
            import psutil  # type: ignore[import-untyped]

            cpu = float(psutil.cpu_percent(interval=None))
            mem = float(psutil.virtual_memory().percent)
            return (cpu, mem)
        except Exception:
            # Fallback baseline when psutil is not available
            return (25.0, 40.0)

    def register_local_worker_start(self) -> None:
        """Increment active local worker count."""
        self._active_local_count += 1

    def register_local_worker_finish(self) -> None:
        """Decrement active local worker count."""
        if self._active_local_count > 0:
            self._active_local_count -= 1

    def sample_watermark(self) -> ResourceWatermark:
        """Capture an instant snapshot of host resource usage and evaluate watermark."""
        cpu, mem = self._sampler()
        if cpu > self._peak_cpu:
            self._peak_cpu = cpu
        if mem > self._peak_memory:
            self._peak_memory = mem

        watermark = ResourceWatermark(
            cpu_percent=cpu,
            memory_percent=mem,
            active_local_workers=self._active_local_count,
            max_recommended_local_workers=self.max_local_workers,
            cpu_threshold_percent=self.cpu_threshold,
            memory_threshold_percent=self.memory_threshold,
            timestamp=time.time(),
        )

        if watermark.is_over_watermark:
            logger.warning(
                "Host resource watermark exceeded! CPU: %.1f%% (max %.1f%%), "
                "Mem: %.1f%% (max %.1f%%), LocalWorkers: %d (max %d). Offloading to cloud.",
                watermark.cpu_percent,
                watermark.cpu_threshold_percent,
                watermark.memory_percent,
                watermark.memory_threshold_percent,
                watermark.active_local_workers,
                watermark.max_recommended_local_workers,
            )

        return watermark

    def get_peak_usage(self) -> tuple[float, float]:
        """Return (peak_cpu_percent, peak_memory_percent)."""
        return (self._peak_cpu, self._peak_memory)

    def reset_peaks(self) -> None:
        """Reset peak metrics counters."""
        self._peak_cpu = 0.0
        self._peak_memory = 0.0

    def evaluate_target(
        self,
        requested_preference: ExecutionTarget | None = None,
    ) -> ExecutionTarget:
        """Determine whether the next subagent task should execute locally or in cloud."""
        if requested_preference == ExecutionTarget.CLOUD_SANDBOX:
            return ExecutionTarget.CLOUD_SANDBOX

        watermark = self.sample_watermark()
        if requested_preference == ExecutionTarget.LOCAL_HOST:
            # If user explicitly preferred local, but host is dangerously overloaded, safety first
            if watermark.cpu_percent >= 95.0 or watermark.memory_percent >= 95.0:
                logger.error("Host at critical 95%+ capacity; overriding explicit local preference.")
                return ExecutionTarget.CLOUD_SANDBOX
            return ExecutionTarget.LOCAL_HOST

        return watermark.recommendation
