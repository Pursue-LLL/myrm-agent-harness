"""Data types and schemas for Tool-Level Circuit Breaker and Graceful Fallback Firewall Suite.

Defines circuit state machine states, fine-grained error categories, execution outcomes,
and telemetry snapshots to guard against retry storms and cascading service collapse.

[INPUT]
- __future__
- time
- dataclasses
- enum

[OUTPUT]
- CircuitState
- ErrorCategory
- CircuitBreakerConfig
- ToolExecutionOutcome
- CircuitBreakerSnapshot

[POS]
Data types and schemas for Tool-Level Circuit Breaker and Graceful Fallback Firewall Suite.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class CircuitState(StrEnum):
    """Lifecycle state of a tool circuit breaker."""

    CLOSED = "closed"  # Normal operating state; requests pass through
    OPEN = "open"  # Tripped open; requests immediately fast-failed or routed to fallback
    HALF_OPEN = "half_open"  # Recovery testing state; single probe request allowed to verify health


class ErrorCategory(StrEnum):
    """Categorization of tool failure modes to enforce strict retry boundaries."""

    RETRYABLE_TRANSIENT = "retryable_transient"  # Network timeouts, socket resets, 429 rate limit, 502/503/504
    NON_RETRYABLE_FATAL = "non_retryable_fatal"  # 400 bad schema, 401/403 auth, file not found, syntax errors


@dataclass(frozen=True)
class CircuitBreakerConfig:
    """Configuration governing circuit breaker tripping, recovery, and retry behavior."""

    failure_threshold: int = 5  # Number of consecutive failures before tripping to OPEN
    recovery_timeout_s: float = 30.0  # Cooldown period before transitioning from OPEN to HALF_OPEN
    max_retries: int = 3  # Maximum retry attempts for transient errors
    base_backoff_s: float = 0.5  # Base backoff multiplier
    max_backoff_s: float = 5.0  # Ceiling cap on backoff delays


@dataclass(frozen=True)
class ToolExecutionOutcome:
    """Terminal outcome of executing a tool under circuit breaker protection."""

    success: bool
    return_value: str = ""
    error_msg: str = ""
    is_fallback: bool = False
    circuit_state: CircuitState = CircuitState.CLOSED
    retries_attempted: int = 0
    duration_s: float = 0.0


@dataclass(frozen=True)
class CircuitBreakerSnapshot:
    """Telemetry status snapshot of a tool circuit breaker."""

    tool_name: str
    state: CircuitState
    consecutive_failures: int
    total_calls: int
    total_failures: int
    total_fallbacks: int
    last_state_change: float = field(default_factory=time.time)
