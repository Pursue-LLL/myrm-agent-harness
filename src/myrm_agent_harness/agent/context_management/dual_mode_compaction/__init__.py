"""Dual-mode proactive watermark compaction and reactive provider 400 self-healing suite.

[INPUT]
-
  agent.context_management.dual_mode_compaction.dual_mode_compaction_suite::DualModeCompactionAndOverflowSelfHealingSuite
  (POS: Main suite orchestrating proactive watermark compaction and reactive provider 400 self-healing.)
- agent.context_management.dual_mode_compaction.dual_mode_compaction_types::CompactableMessage,
  CompactionExecutionResult, CompactionTriggerKind, ContextWindowBudgetConfig, ProviderOverflowKind,
  SelfHealingAuditReceipt (POS: Types and schemas for proactive watermark compaction and reactive 400
  self-healing.)
- agent.context_management.dual_mode_compaction.overflow_detector::ProviderOverflowDetector (POS: Precision
  detector for provider 400 Bad Request and context window overflow errors.)

[OUTPUT]
- Re-exports: CompactableMessage, CompactionExecutionResult, CompactionTriggerKind, ContextWindowBudgetConfig,
  DualModeCompactionAndOverflowSelfHealingSuite, ProviderOverflowDetector, ProviderOverflowKind,
  SelfHealingAuditReceipt

[POS]
Dual-mode proactive watermark compaction and reactive provider 400 self-healing suite.
"""

from __future__ import annotations

from .dual_mode_compaction_suite import DualModeCompactionAndOverflowSelfHealingSuite
from .dual_mode_compaction_types import (
    CompactableMessage,
    CompactionExecutionResult,
    CompactionTriggerKind,
    ContextWindowBudgetConfig,
    ProviderOverflowKind,
    SelfHealingAuditReceipt,
)
from .overflow_detector import ProviderOverflowDetector

__all__ = [
    "CompactableMessage",
    "CompactionExecutionResult",
    "CompactionTriggerKind",
    "ContextWindowBudgetConfig",
    "DualModeCompactionAndOverflowSelfHealingSuite",
    "ProviderOverflowDetector",
    "ProviderOverflowKind",
    "SelfHealingAuditReceipt",
]
