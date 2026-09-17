"""Resilience subsystem for autonomous error self-correction and execution budget governance.

[INPUT]
- agent.resilience.budget_controller::DynamicExecutionBudgetController,
  ExecutionBudgetSnapshot (POS: 动态执行预算控制层)
- agent.resilience.checkpointer::MarathonCheckpointer, MarathonCheckpointRecord
  (POS: 长任务检查点持久化层)
- agent.resilience.error_recovery::ErrorSelfCorrectionGovernor
  (POS: 错误自纠正治理层)
- agent.resilience.types::DiagnosticHypothesis, ErrorCorrectionOutcome,
  ExecutionBudgetConfig, RecoveryActionType (POS: 韧性子系统数据契约层)

[OUTPUT]
- Budget controller, marathon checkpointer, error-recovery governor and their types

[POS]
Public surface of the resilience subpackage. Lets a long run recover from faults and stay
inside a bounded tool/step budget without restarting the task from scratch.
"""

from myrm_agent_harness.agent.resilience.budget_controller import (
    DynamicExecutionBudgetController,
    ExecutionBudgetSnapshot,
)
from myrm_agent_harness.agent.resilience.checkpointer import (
    MarathonCheckpointer,
    MarathonCheckpointRecord,
)
from myrm_agent_harness.agent.resilience.error_recovery import (
    ErrorSelfCorrectionGovernor,
)
from myrm_agent_harness.agent.resilience.types import (
    DiagnosticHypothesis,
    ErrorCorrectionOutcome,
    ExecutionBudgetConfig,
    RecoveryActionType,
)

__all__ = [
    "DiagnosticHypothesis",
    "DynamicExecutionBudgetController",
    "ErrorCorrectionOutcome",
    "ErrorSelfCorrectionGovernor",
    "ExecutionBudgetConfig",
    "ExecutionBudgetSnapshot",
    "MarathonCheckpointer",
    "MarathonCheckpointRecord",
    "RecoveryActionType",
]
