"""Resilience subsystem for autonomous error self-correction.

[INPUT]
- agent.resilience.error_recovery::ErrorSelfCorrectionGovernor
  (POS: 错误自纠正治理层)
- agent.resilience.types::DiagnosticHypothesis, ErrorCorrectionOutcome,
  RecoveryActionType (POS: 韧性子系统数据契约层)

[OUTPUT]
- Error-recovery governor and its types

[POS]
Public surface of the resilience subpackage. Lets a long run diagnose a failing tool call and
self-correct without restarting the task from scratch.
"""

from myrm_agent_harness.agent.resilience.error_recovery import (
    ErrorSelfCorrectionGovernor,
)
from myrm_agent_harness.agent.resilience.types import (
    DiagnosticHypothesis,
    ErrorCorrectionOutcome,
    RecoveryActionType,
)

__all__ = [
    "DiagnosticHypothesis",
    "ErrorCorrectionOutcome",
    "ErrorSelfCorrectionGovernor",
    "RecoveryActionType",
]
