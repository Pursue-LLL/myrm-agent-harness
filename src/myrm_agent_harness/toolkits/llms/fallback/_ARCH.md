# fallback/

## Overview
Enhanced model fallback management. Supports cooldown periods, candidate pools, and decision logging.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Enhanced model fallback management. Supports cooldown periods, candidate pools, and decision logging | ✅ |
| circuit_breaker.py | Core | Circuit breaker. Opens after consecutive failures to prevent cascading failures. | ✅ |
| config.py | Config | Configurable probe and cooldown policies for model fallback management. | ✅ |
| context.py | Core | Async-context-bound emitter binding via ContextVar. Lets business surfaces (SSE, telemetry) subscribe to failover/recovery events without coupling the manager to any transport. | ✅ |
| events.py | Core | Defines failover and recovery events that are emitted during model lifecycle. | ✅ |
| health_check.py | Core | Lightweight health check. Uses 1-token test to minimize probing cost. | ✅ |
| logger.py | Core | Fallback decision logger. Structured logging of each fallback attempt and decision for tracing and a | ✅ |
| managed_llm.py | Core | LLM wrapper that transparently integrates ModelFallbackManager into LangChain's | ✅ |
| manager.py | Core | Model fallback manager. Maintains candidate pool, cooldown state, and selects the next available mod | ✅ |
| presets.py | Core | Preset fallback strategies for common use cases. Provides best-practice | ✅ |
| probe_throttle.py | Core | Global probe throttle. Prevents concurrent requests from redundantly probing the same model. | ✅ |
| recommendations.py | Core | Provides intelligent fallback model recommendations based on model capabilities, | ✅ |
| scenario.py | Core | Scenario-aware model selection. Optimizes model choice based on scenario (realtime/batch/balanced). | ✅ |

## Key Dependencies

- `infra`
