# core/security/autonomy/

## Overview
Data-driven autonomy level escalation (L1-L5), sliding-window promotion gate, and exception circuit breaker governance suite.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Public export facade for autonomy governance primitives. | — |
| `models.py` | Core | AutonomyLevel, BreakerState, AutonomyMetrics, AutonomyBreakerEvent, and AutonomyPromotionResult data contracts. | ✅ |
| `gate_calculator.py` | Core | Thread-safe sliding-window metrics evaluator preventing Goodhart gaming and premature escalation. | ✅ |
| `circuit_breaker.py` | Core | 3-state circuit breaker state machine (CLOSED, OPEN, HALF_OPEN) enforcing instant fallback on repetitive errors. | ✅ |
| `interceptor.py` | Core | Execution interceptor tying permission gating, breaker tripping, and organization ceiling capping. | ✅ |

## Consumers
- Runtime tool dispatch and execution pipeline
- Session telemetry exporter and circuit breaker alert channel
