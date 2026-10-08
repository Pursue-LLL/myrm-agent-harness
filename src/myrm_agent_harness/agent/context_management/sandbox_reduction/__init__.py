"""In-Sandbox Data Reduction and Session Action Ledger Suite (Item 221).

Exports contracts and the core engine for in-sandbox output truncation,
diff distillation, and SQLite-backed fine-grained execution transaction ledgers.

[INPUT]
- agent.context_management.sandbox_reduction.sandbox_reduction_engine::InSandboxDataReductionEngine (POS: Core
  engine for In-Sandbox Data Reduction and Session Action Ledger (Item 221).)
- agent.context_management.sandbox_reduction.sandbox_reduction_types::ActionKind, ActionLedgerEntry,
  LedgerQueryResult, ReducedOutputEnvelope, ReductionKind, SandboxReductionConfig (POS: Strongly typed
  contracts for In-Sandbox Data Reduction and Session Action Ledger (Item 221).)

[OUTPUT]
- Re-exports: ActionKind, ActionLedgerEntry, InSandboxDataReductionEngine, LedgerQueryResult,
  ReducedOutputEnvelope, ReductionKind, SandboxReductionConfig

[POS]
In-Sandbox Data Reduction and Session Action Ledger Suite (Item 221).
"""

from __future__ import annotations

from .sandbox_reduction_engine import InSandboxDataReductionEngine
from .sandbox_reduction_types import (
    ActionKind,
    ActionLedgerEntry,
    LedgerQueryResult,
    ReducedOutputEnvelope,
    ReductionKind,
    SandboxReductionConfig,
)

__all__ = [
    "ActionKind",
    "ActionLedgerEntry",
    "InSandboxDataReductionEngine",
    "LedgerQueryResult",
    "ReducedOutputEnvelope",
    "ReductionKind",
    "SandboxReductionConfig",
]
