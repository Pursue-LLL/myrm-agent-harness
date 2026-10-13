# resilience/

## Overview
Harness resilience subsystem providing autonomous error self-correction and the unattended-run task airbag.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Exports resilience types and `ErrorSelfCorrectionGovernor` | — |
| `types.py` | Types | Domain models: `RecoveryActionType`, `DiagnosticHypothesis`, `ErrorCorrectionOutcome` | ✅ |
| `error_recovery.py` | Core | `ErrorSelfCorrectionGovernor` autonomous diagnosis, hypothesis testing, and error recovery engine | ✅ |
| `task_airbag.py` | Core | 长任务与无人值守挂机安全气囊管理器（双轨自适应快照武装、反向 Diff 账本汇总、翻车现场救援快照捕获与原子时光倒流一键重置） | ✅ |

## Architecture Alignment
- Pure Harness execution layer: Zero dependencies on server API or WebUI routes.
- Prompt cache integrity: Diagnostic self-healing hints are injected exclusively into tool error outputs, preserving static system prompt cache prefixes.
