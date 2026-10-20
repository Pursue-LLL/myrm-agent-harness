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
| `failure_reasons.py` | Core | 闭集强类型失败原因分级裁决与三态重试决策枚举模块。 | ✅ |
| `in_session_compactor.py` | Core | 同会话就地轨迹关键帧三明治压缩器模块。 | ✅ |
| `long_horizon_guard_middleware.py` | Core | Long Horizon Execution Guard Middleware and Terminal Output Barrier Governor. | ✅ |
| `retry_governor.py` | Core | 工业级弹性重试调度治理器模块。 | ✅ |
| `terminal_output_barrier.py` | Core | Terminal Output Barrier and Long Horizon Execution Guard. | ✅ |

## Architecture Alignment
- Pure Harness execution layer: Zero dependencies on server API or WebUI routes.
- Prompt cache integrity: Diagnostic self-healing hints are injected exclusively into tool error outputs, preserving static system prompt cache prefixes.
