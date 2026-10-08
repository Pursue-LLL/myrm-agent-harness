"""Layered loop termination semantics, paired events, and debt inbox package.

[INPUT]
- agent.context_management.layered_loop_termination.debt_inbox_manager::DebtInboxManager (POS: Manager for
  consumable debt inbox and model response debt accounting.)
-
  agent.context_management.layered_loop_termination.layered_loop_termination_suite::LayeredLoopTerminationAndDebtInboxSuite
  (POS: Suite managing paired layered loop lifecycle events, dual-condition termination, and stop hooks.)
- agent.context_management.layered_loop_termination.layered_loop_types::DebtInboxItem, DebtKind,
  LayeredLoopEvent, LoopHierarchyTier, LoopTerminationDecision, LoopTerminationReason (POS: Types for layered
  loop termination, paired lifecycle events, and debt inbox.)

[OUTPUT]
- Re-exports: DebtInboxItem, DebtInboxManager, DebtKind, LayeredLoopEvent,
  LayeredLoopTerminationAndDebtInboxSuite, LoopHierarchyTier, LoopTerminationDecision, LoopTerminationReason

[POS]
Layered loop termination semantics, paired events, and debt inbox package.
"""

from __future__ import annotations

from .debt_inbox_manager import DebtInboxManager
from .layered_loop_termination_suite import (
    LayeredLoopTerminationAndDebtInboxSuite,
)
from .layered_loop_types import (
    DebtInboxItem,
    DebtKind,
    LayeredLoopEvent,
    LoopHierarchyTier,
    LoopTerminationDecision,
    LoopTerminationReason,
)

__all__ = [
    "DebtInboxItem",
    "DebtInboxManager",
    "DebtKind",
    "LayeredLoopEvent",
    "LayeredLoopTerminationAndDebtInboxSuite",
    "LoopHierarchyTier",
    "LoopTerminationDecision",
    "LoopTerminationReason",
]
