# core/security/commerce_dispute_escrow/

## Overview
Agent commerce dispute escrow manager and transaction circuit breaker evaluator.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Public exports for CommerceEscrowManager, CommerceCircuitBreakerEvaluator, and types. | — |
| `types.py` | Types | Domain models for escrow agreements, disputes, task types, and circuit breakers. | ✅ |
| `evaluator.py` | Core | Circuit breaker policy evaluator assessing maximum exposure and loss thresholds. | ✅ |
| `manager.py` | Core | Escrow lifecycle manager handling commitments, disputes, and releases. | ✅ |

## Dependencies
- Standard library: `dataclasses`, `enum`, `time`
- No internal harness coupling.
