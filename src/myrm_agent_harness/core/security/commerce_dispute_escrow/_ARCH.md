# core/security/commerce_dispute_escrow/

## Overview
Agent commerce dispute escrow manager and transaction circuit breaker evaluator.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Public exports for CommerceEscrowManager, CommerceCircuitBreakerEvaluator, and types. | — |
| `types.py` | Types | Domain models for escrow agreements, disputes, task types, and circuit breakers. | ✅ |
| `circuit_breaker.py` | Core | `CommerceCircuitBreakerEvaluator`: quantitative gate that freezes capital operations when loss / position / exposure telemetry crosses `TradingCircuitBreakers` thresholds. | ✅ |
| `engine.py` | Core | Deterministic escrow protocol engine: escrow creation, deliverable submission, dispute raising, arbitrator vote commitments and fund distribution. | ✅ |

## Dependencies
- Standard library: `dataclasses`, `enum`, `time`
- No internal harness coupling.
