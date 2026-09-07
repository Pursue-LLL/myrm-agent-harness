"""# Marathon Task Resilience and Error Self-Correction Architecture

## Overview
Harness resilience subsystem providing multi-hour autonomous recovery, execution budgeting, and resilient state checkpointing.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Exports resilience types, `ErrorSelfCorrectionGovernor`, `DynamicExecutionBudgetController`, `MarathonCheckpointer` | — |
| `types.py` | Types | Domain models: `RecoveryActionType`, `DiagnosticHypothesis`, `ErrorCorrectionOutcome`, `ExecutionBudgetConfig` | ✅ |
| `error_recovery.py` | Core | `ErrorSelfCorrectionGovernor` autonomous diagnosis, hypothesis testing, and error recovery engine | ✅ |
| `budget_controller.py` | Core | `DynamicExecutionBudgetController` tracking step quotas, token velocity, and circuit breakers | ✅ |
| `checkpointer.py` | Core | `MarathonCheckpointer` durable atomic task checkpoint manager with crash recovery | ✅ |

## Architecture Alignment
- Pure Harness execution layer: Zero dependencies on server API or WebUI routes.
- Prompt cache integrity: Diagnostic self-healing hints are injected exclusively into tool error outputs, preserving static system prompt cache prefixes.
"""
