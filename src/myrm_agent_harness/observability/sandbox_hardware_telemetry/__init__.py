"""[INPUT] Dynamic hardware telemetry metrics and circuit breaker commands.
[OUTPUT] Public facade exporting three-tier runaway circuit breaker abstractions and singleton instance.
[POS] myrm_agent_harness.observability.sandbox_hardware_telemetry

Exposes:
- Models: CircuitBreakerLevel, CircuitBreakerConfig, CircuitBreakerEvaluation, HardwareMetricSample, HardwareTelemetrySnapshot
- Engine: SandboxHardwareCircuitBreaker, get_default_hardware_circuit_breaker
"""

from .circuit_breaker import (
    SandboxHardwareCircuitBreaker,
    get_default_hardware_circuit_breaker,
)
from .models import (
    CircuitBreakerConfig,
    CircuitBreakerEvaluation,
    CircuitBreakerLevel,
    HardwareMetricSample,
    HardwareTelemetrySnapshot,
)

__all__ = [
    "CircuitBreakerConfig",
    "CircuitBreakerEvaluation",
    "CircuitBreakerLevel",
    "HardwareMetricSample",
    "HardwareTelemetrySnapshot",
    "SandboxHardwareCircuitBreaker",
    "get_default_hardware_circuit_breaker",
]
