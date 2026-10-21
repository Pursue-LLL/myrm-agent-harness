"""System load sensors for different deployment modes.

Provides cross-platform hardware sensing (Local/Tauri) and API-quota sensing (SaaS).
Unlike gbrain's broken `os.loadavg()` approach (returns [0,0,0] on Windows),
we use `psutil` which works reliably across all platforms.

[INPUT]
- (none)

[OUTPUT]
- DeviceLoadSensor: Load sensor for Local/Tauri desktop deployment.
- SaaSLoadSensor: Load sensor for SaaS multi-tenant deployment.

[POS]
System load sensors for different deployment modes.
"""

from __future__ import annotations

import os
import time

from .protocols import LoadSensor, SystemLoadLevel, SystemLoadSnapshot

try:
    import psutil
except (ImportError, TypeError):
    psutil = None  # type: ignore[assignment]


class DeviceLoadSensor(LoadSensor):
    """Load sensor for Local/Tauri desktop deployment.

    Reads real CPU and memory usage.
    - In Docker/K8s: Reads cgroup v1/v2 metrics for accurate container limits.
    - Local/Bare-metal: Fallback to psutil (cross-platform: Win/Mac/Linux).

    Classifies system load into 4 levels based on configurable thresholds.
    Includes Exponential Moving Average (EMA) smoothing to prevent spurious 429s
    from instantaneous CPU spikes.
    """

    def __init__(
        self,
        *,
        cpu_busy_pct: float = 60.0,
        cpu_overloaded_pct: float = 85.0,
        memory_busy_pct: float = 75.0,
        memory_overloaded_pct: float = 90.0,
        ema_alpha: float = 0.3,
    ) -> None:
        self._cpu_busy = cpu_busy_pct
        self._cpu_overloaded = cpu_overloaded_pct
        self._mem_busy = memory_busy_pct
        self._mem_overloaded = memory_overloaded_pct
        self._ema_alpha = ema_alpha

        self._smoothed_cpu: float | None = None
        self._smoothed_mem: float | None = None

        # For cgroup CPU delta calculation
        self._last_cpu_usage_usec: float | None = None
        self._last_cpu_read_time: float | None = None

    def _read_file_int(self, path: str) -> int | None:
        try:
            with open(path, encoding="utf-8") as f:
                val = f.read().strip()
                return int(val) if val.isdigit() else None
        except Exception:
            return None

    def _get_cgroup_metrics(self) -> tuple[float | None, float | None]:
        """Read cgroup v1 or v2 limits if running inside a container."""
        cpu_pct: float | None = None
        mem_pct: float | None = None

        try:
            # --- Memory ---
            # Try cgroup v2 first
            if os.path.exists("/sys/fs/cgroup/memory.current") and os.path.exists("/sys/fs/cgroup/memory.max"):
                current = self._read_file_int("/sys/fs/cgroup/memory.current")
                try:
                    with open("/sys/fs/cgroup/memory.max", encoding="utf-8") as f:
                        max_str = f.read().strip()
                        if max_str != "max" and current is not None:
                            mem_pct = (current / int(max_str)) * 100.0
                except Exception:
                    pass
            # Fallback to cgroup v1
            elif os.path.exists("/sys/fs/cgroup/memory/memory.usage_in_bytes") and os.path.exists(
                "/sys/fs/cgroup/memory/memory.limit_in_bytes"
            ):
                current = self._read_file_int("/sys/fs/cgroup/memory/memory.usage_in_bytes")
                limit = self._read_file_int("/sys/fs/cgroup/memory/memory.limit_in_bytes")
                # cgroup v1 often sets limit to a huge number (e.g., 9223372036854771712) if unbounded
                if current is not None and limit is not None and limit < 1024**4:  # Assume < 1TB is a real limit
                    mem_pct = (current / limit) * 100.0

            # --- CPU ---
            usage_usec: float | None = None
            cpus_allowed: float | None = None

            # Try cgroup v2
            if os.path.exists("/sys/fs/cgroup/cpu.stat") and os.path.exists("/sys/fs/cgroup/cpu.max"):
                try:
                    with open("/sys/fs/cgroup/cpu.max", encoding="utf-8") as f:
                        parts = f.read().strip().split()
                        if len(parts) == 2 and parts[0] != "max":
                            cpus_allowed = int(parts[0]) / int(parts[1])
                    if cpus_allowed:
                        with open("/sys/fs/cgroup/cpu.stat", encoding="utf-8") as f:
                            for line in f:
                                if line.startswith("usage_usec"):
                                    usage_usec = int(line.split()[1])
                                    break
                except Exception:
                    pass
            # Fallback to cgroup v1
            elif os.path.exists("/sys/fs/cgroup/cpu/cpuacct.usage") and os.path.exists(
                "/sys/fs/cgroup/cpu/cpu.cfs_quota_us"
            ):
                quota = self._read_file_int("/sys/fs/cgroup/cpu/cpu.cfs_quota_us")
                period = self._read_file_int("/sys/fs/cgroup/cpu/cpu.cfs_period_us")
                if quota is not None and period is not None and quota > 0:
                    cpus_allowed = quota / period
                    # cpuacct.usage is in nanoseconds, convert to microseconds to match v2 logic
                    ns = self._read_file_int("/sys/fs/cgroup/cpu/cpuacct.usage")
                    if ns is not None:
                        usage_usec = ns / 1000.0

            # Calculate CPU percentage based on delta
            now = time.monotonic()
            if usage_usec is not None and cpus_allowed is not None:
                if self._last_cpu_usage_usec is not None and self._last_cpu_read_time is not None:
                    time_delta_sec = now - self._last_cpu_read_time
                    usage_delta_sec = (usage_usec - self._last_cpu_usage_usec) / 1_000_000.0
                    if time_delta_sec > 0:
                        # usage_delta_sec is total CPU seconds used. Divide by wall time * cpus_allowed
                        cpu_pct = (usage_delta_sec / (time_delta_sec * cpus_allowed)) * 100.0
                        cpu_pct = min(100.0, max(0.0, cpu_pct))  # Clamp 0-100

                self._last_cpu_usage_usec = usage_usec
                self._last_cpu_read_time = now

        except Exception:
            pass  # Silently fallback to psutil on any parsing error

        return cpu_pct, mem_pct

    def read(self) -> SystemLoadSnapshot:
        if psutil is None:
            return SystemLoadSnapshot(
                level=SystemLoadLevel.NORMAL,
                detail="psutil unavailable, assuming NORMAL",
            )

        cgroup_cpu, cgroup_mem = self._get_cgroup_metrics()

        raw_cpu = cgroup_cpu if cgroup_cpu is not None else psutil.cpu_percent(interval=0)
        raw_mem = cgroup_mem if cgroup_mem is not None else psutil.virtual_memory().percent

        # Apply Exponential Moving Average (EMA) for smoothing
        if self._smoothed_cpu is None:
            self._smoothed_cpu = raw_cpu
        else:
            self._smoothed_cpu = self._ema_alpha * raw_cpu + (1 - self._ema_alpha) * self._smoothed_cpu

        if self._smoothed_mem is None:
            self._smoothed_mem = raw_mem
        else:
            self._smoothed_mem = self._ema_alpha * raw_mem + (1 - self._ema_alpha) * self._smoothed_mem

        level = self._classify(self._smoothed_cpu, self._smoothed_mem)

        return SystemLoadSnapshot(
            level=level,
            cpu_percent=self._smoothed_cpu,
            memory_percent=self._smoothed_mem,
            detail=f"cpu={self._smoothed_cpu:.0f}% (raw={raw_cpu:.0f}%) mem={self._smoothed_mem:.0f}% (raw={raw_mem:.0f}%)",
            timestamp=time.monotonic(),
        )

    def _classify(self, cpu: float, mem: float) -> SystemLoadLevel:
        if cpu >= self._cpu_overloaded or mem >= self._mem_overloaded:
            return SystemLoadLevel.OVERLOADED
        if cpu >= self._cpu_busy or mem >= self._mem_busy:
            return SystemLoadLevel.BUSY
        if cpu < 15.0 and mem < 50.0:
            return SystemLoadLevel.IDLE
        return SystemLoadLevel.NORMAL


class SaaSLoadSensor(LoadSensor):
    """Load sensor for SaaS multi-tenant deployment.

    Instead of reading hardware metrics, monitors API quota headroom.
    The `api_quota_remaining_pct` is injected by the control plane
    based on the current LLM provider's rate-limit counters.
    """

    def __init__(self) -> None:
        self._api_quota_remaining_pct: float = 100.0
        self._queue_depth: int = 0
        self._last_update: float = 0.0

    def update(
        self,
        api_quota_remaining_pct: float,
        queue_depth: int = 0,
    ) -> None:
        """Called by the control plane to push latest quota metrics."""
        self._api_quota_remaining_pct = api_quota_remaining_pct
        self._queue_depth = queue_depth
        self._last_update = time.monotonic()

    def read(self) -> SystemLoadSnapshot:
        staleness = time.monotonic() - self._last_update if self._last_update > 0 else float("inf")
        if staleness > 120:
            return SystemLoadSnapshot(
                level=SystemLoadLevel.NORMAL,
                api_quota_remaining_pct=self._api_quota_remaining_pct,
                detail=f"stale data ({staleness:.0f}s), assuming NORMAL",
            )

        level = self._classify()
        return SystemLoadSnapshot(
            level=level,
            api_quota_remaining_pct=self._api_quota_remaining_pct,
            detail=f"api_quota={self._api_quota_remaining_pct:.0f}% queue={self._queue_depth}",
            timestamp=time.monotonic(),
        )

    def _classify(self) -> SystemLoadLevel:
        q = self._api_quota_remaining_pct
        if q < 10 or self._queue_depth > 100:
            return SystemLoadLevel.OVERLOADED
        if q < 30 or self._queue_depth > 50:
            return SystemLoadLevel.BUSY
        if q > 80 and self._queue_depth < 5:
            return SystemLoadLevel.IDLE
        return SystemLoadLevel.NORMAL
