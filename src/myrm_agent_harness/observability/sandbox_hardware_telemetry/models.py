"""[INPUT] Dynamic sandbox hardware resource telemetry samples (CPU, memory, disk, network).
[OUTPUT] Immutable telemetry data structures and three-tier runaway circuit breaker evaluation models.
[POS] myrm_agent_harness.observability.sandbox_hardware_telemetry.models

Defines models for sandbox hardware telemetry and three-tier runaway circuit breaking:
1. HardwareMetricSample: CPU%, RAM (bytes/percent), Disk (bytes/percent), Network I/O.
2. CircuitBreakerLevel: NORMAL (safe), WARNING (80%), SUSPENDED (90%), TRIPPED (95%/hard kill).
3. CircuitBreakerConfig: Configurable multi-tier thresholds and maximum execution duration.
4. CircuitBreakerEvaluation: Incident snapshot with triggered rule, violation details, and mitigation action.
"""

from dataclasses import dataclass, field
from enum import Enum
import time


class CircuitBreakerLevel(str, Enum):
    """Three-tier laddered runaway safety levels."""

    NORMAL = "normal"         # <80% usage: normal pass-through
    WARNING = "warning"       # >=80% usage: amber warning nudge emitted
    SUSPENDED = "suspended"   # >=90% usage: task execution frozen for manual intervention
    TRIPPED = "tripped"       # >=95% usage or quota exhausted: hard graceful termination


@dataclass(frozen=True)
class HardwareMetricSample:
    """Individual hardware resource usage metric reading."""

    cpu_percent: float
    memory_used_bytes: int
    memory_total_bytes: int
    memory_percent: float
    disk_used_bytes: int
    disk_total_bytes: int
    disk_percent: float
    network_bytes_sent: int = 0
    network_bytes_recv: int = 0
    timestamp_ms: int = field(default_factory=lambda: int(time.time() * 1000))

    def to_dict(self) -> dict[str, float | int]:
        return {
            "cpu_percent": round(self.cpu_percent, 2),
            "memory_used_bytes": self.memory_used_bytes,
            "memory_total_bytes": self.memory_total_bytes,
            "memory_percent": round(self.memory_percent, 2),
            "disk_used_bytes": self.disk_used_bytes,
            "disk_total_bytes": self.disk_total_bytes,
            "disk_percent": round(self.disk_percent, 2),
            "network_bytes_sent": self.network_bytes_sent,
            "network_bytes_recv": self.network_bytes_recv,
            "timestamp_ms": self.timestamp_ms,
        }


@dataclass(frozen=True)
class CircuitBreakerConfig:
    """Configurable multi-tier runaway trip thresholds."""

    warning_cpu_threshold: float = 80.0
    suspend_cpu_threshold: float = 90.0
    trip_cpu_threshold: float = 95.0
    warning_mem_threshold: float = 80.0
    suspend_mem_threshold: float = 90.0
    trip_mem_threshold: float = 95.0
    max_consecutive_violations: int = 3
    max_task_duration_seconds: float = 600.0

    def to_dict(self) -> dict[str, float | int]:
        return {
            "warning_cpu_threshold": self.warning_cpu_threshold,
            "suspend_cpu_threshold": self.suspend_cpu_threshold,
            "trip_cpu_threshold": self.trip_cpu_threshold,
            "warning_mem_threshold": self.warning_mem_threshold,
            "suspend_mem_threshold": self.suspend_mem_threshold,
            "trip_mem_threshold": self.trip_mem_threshold,
            "max_consecutive_violations": self.max_consecutive_violations,
            "max_task_duration_seconds": self.max_task_duration_seconds,
        }


@dataclass(frozen=True)
class CircuitBreakerEvaluation:
    """Result of evaluating a hardware sample against circuit breaker thresholds."""

    level: CircuitBreakerLevel
    triggered_metric: str
    current_value: float
    threshold_value: float
    action_description: str
    sample: HardwareMetricSample
    evaluated_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))

    def to_dict(self) -> dict[str, str | float | int | dict[str, float | int]]:
        return {
            "level": self.level.value,
            "triggered_metric": self.triggered_metric,
            "current_value": round(self.current_value, 2),
            "threshold_value": round(self.threshold_value, 2),
            "action_description": self.action_description,
            "sample": self.sample.to_dict(),
            "evaluated_at_ms": self.evaluated_at_ms,
        }


@dataclass(frozen=True)
class HardwareTelemetrySnapshot:
    """Aggregated cockpit snapshot combining hardware telemetry, circuit breaker state, and history."""

    latest_sample: HardwareMetricSample | None
    current_level: CircuitBreakerLevel
    config: CircuitBreakerConfig
    consecutive_violations: int
    incident_history: tuple[CircuitBreakerEvaluation, ...]
    generated_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))

    def to_dict(self) -> dict[str, str | int | dict[str, float | int] | list[dict[str, str | float | int | dict[str, float | int]]] | None]:
        return {
            "latest_sample": self.latest_sample.to_dict() if self.latest_sample else None,
            "current_level": self.current_level.value,
            "config": self.config.to_dict(),
            "consecutive_violations": self.consecutive_violations,
            "incident_history": [i.to_dict() for i in self.incident_history],
            "generated_at_ms": self.generated_at_ms,
        }
