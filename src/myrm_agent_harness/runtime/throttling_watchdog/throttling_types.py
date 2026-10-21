"""Strongly typed contracts for sandbox resource affinity and adaptive CPU/RAM watchdog.

Benchmarked against production anti-lockup invariants for intensive media and local model tasks:
- Process priority degradation (Nice values) to protect desktop UI and host responsiveness.
- Adaptive CPU throttling to prevent host lockup under ffmpeg or transcription spikes.
- Low-memory watermark protection to prevent kernel OOM-killer crashes.

[OUTPUT]
- ProcessPriorityLevel: Operating system scheduling priority levels.
- ThrottleAction: Remediation actions dispatched by the watchdog.
- SystemLoadSnapshot: Real-time host load metrics and threshold breaches.
- WatchdogVerdict: Evaluated pacing and concurrency constraints for sandbox execution.

[INPUT]
- __future__
- time
- dataclasses
- enum

[OUTPUT]
- ProcessPriorityLevel
- ThrottleAction
- SystemLoadSnapshot
- WatchdogVerdict

[POS]
Strongly typed contracts for sandbox resource affinity and adaptive CPU/RAM watchdog.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, StrEnum


class ProcessPriorityLevel(int, Enum):
    """POSIX Nice scheduling priorities for background processes.

    Higher numeric values represent lower scheduling priority, allowing foreground
    desktop processes (window managers, mouse rendering, user terminals) to retain CPU cycles.
    """

    FOREGROUND_NORMAL = 0
    BACKGROUND_LOW = 10
    IDLE_LOWEST = 19


class ThrottleAction(StrEnum):
    """Action directive determined by the adaptive watchdog."""

    NO_ACTION = "no_action"
    THROTTLE_SLEEP = "throttle_sleep"
    SERIALIZE_CONCURRENCY = "serialize_concurrency"


@dataclass(frozen=True)
class SystemLoadSnapshot:
    """Instantaneous snapshot of host resource metrics."""

    cpu_percent: float
    available_ram_bytes: int
    is_cpu_critical: bool
    is_ram_critical: bool
    timestamp: float = field(default_factory=time.time)

    @classmethod
    def capture(
        cls,
        cpu_percent: float,
        available_ram_bytes: int,
        cpu_critical_threshold: float = 85.0,
        ram_critical_watermark: int = 2 * 1024 * 1024 * 1024,
    ) -> SystemLoadSnapshot:
        """Construct snapshot and evaluate critical threshold crossings."""
        return cls(
            cpu_percent=cpu_percent,
            available_ram_bytes=available_ram_bytes,
            is_cpu_critical=cpu_percent >= cpu_critical_threshold,
            is_ram_critical=available_ram_bytes < ram_critical_watermark,
        )


@dataclass(frozen=True)
class WatchdogVerdict:
    """Actionable concurrency and pacing decision produced by the watchdog."""

    verdict_id: str
    action: ThrottleAction
    applied_delay_seconds: float
    max_allowed_concurrency: int
    reason: str
    timestamp: float = field(default_factory=time.time)
