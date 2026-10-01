"""Data-driven autonomy level escalation and exception circuit breaker governance suite.

Exports foundational protocols, sliding-window gate calculators, and breaker interceptors.
"""

from __future__ import annotations

from myrm_agent_harness.core.security.autonomy.circuit_breaker import (
    DEFAULT_COOLDOWN_SECONDS,
    DEFAULT_FAILURE_THRESHOLD,
    DEFAULT_RECOVERY_THRESHOLD,
    AutonomyCircuitBreaker,
)
from myrm_agent_harness.core.security.autonomy.gate_calculator import (
    DEFAULT_MIN_SAMPLES_FOR_PROMOTION,
    DEFAULT_REQUIRED_MUTATION_RATIO,
    DEFAULT_REQUIRED_SUCCESS_RATE,
    DEFAULT_WINDOW_CAPACITY,
    PromotionGateCalculator,
)
from myrm_agent_harness.core.security.autonomy.interceptor import (
    AutonomyExecutionInterceptor,
)
from myrm_agent_harness.core.security.autonomy.models import (
    AutonomyBreakerEvent,
    AutonomyLevel,
    AutonomyMetrics,
    AutonomyPromotionResult,
    BreakerState,
)

__all__ = [
    "AutonomyBreakerEvent",
    "AutonomyCircuitBreaker",
    "AutonomyExecutionInterceptor",
    "AutonomyLevel",
    "AutonomyMetrics",
    "AutonomyPromotionResult",
    "BreakerState",
    "DEFAULT_COOLDOWN_SECONDS",
    "DEFAULT_FAILURE_THRESHOLD",
    "DEFAULT_MIN_SAMPLES_FOR_PROMOTION",
    "DEFAULT_RECOVERY_THRESHOLD",
    "DEFAULT_REQUIRED_MUTATION_RATIO",
    "DEFAULT_REQUIRED_SUCCESS_RATE",
    "DEFAULT_WINDOW_CAPACITY",
    "PromotionGateCalculator",
]
