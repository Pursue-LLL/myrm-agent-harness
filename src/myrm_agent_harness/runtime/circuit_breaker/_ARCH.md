# circuit_breaker/

## Overview
Tool-Level Circuit Breaker and Graceful Fallback Firewall Suite.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Tool-Level Circuit Breaker and Graceful Fallback Firewall Suite. | — |
| `circuit_breaker_types.py` | Core | Data types and schemas for Tool-Level Circuit Breaker and Graceful Fallback Firewall Suite. | ✅ |
| `error_classifier_and_backoff.py` | Core | Fine-grained error classifier and Full Jitter exponential backoff engine. | ✅ |
| `graceful_fallback_firewall.py` | Core | Graceful fallback firewall coordinator for resilient agent tool calling. | ✅ |
| `tool_circuit_breaker.py` | Core | Tool-level adaptive circuit breaker with state machine and retry execution. | ✅ |
