"""Tool-Level Circuit Breaker and Graceful Fallback Firewall Suite.

Guards against retry storms via full jitter backoff, stateful circuit breaking
(CLOSED, OPEN, HALF_OPEN), and structured semantic fallback synthesis.

[INPUT]
- circuit_breaker_types
- error_classifier_and_backoff
- graceful_fallback_firewall
- tool_circuit_breaker

[OUTPUT]
- (模块级副作用与注册)

[POS]
Tool-Level Circuit Breaker and Graceful Fallback Firewall Suite.
"""

from .circuit_breaker_types import (
    CircuitBreakerConfig,
    CircuitBreakerSnapshot,
    CircuitState,
    ErrorCategory,
    ToolExecutionOutcome,
)
from .error_classifier_and_backoff import (
    ErrorClassifier,
    FullJitterBackoff,
)
from .graceful_fallback_firewall import GracefulFallbackFirewall
from .tool_circuit_breaker import ToolCircuitBreaker

__all__ = [
    "CircuitBreakerConfig",
    "CircuitBreakerSnapshot",
    "CircuitState",
    "ErrorCategory",
    "ErrorClassifier",
    "FullJitterBackoff",
    "GracefulFallbackFirewall",
    "ToolCircuitBreaker",
    "ToolExecutionOutcome",
]
