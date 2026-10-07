"""In-Sandbox Data Reduction and Session Action Ledger Suite (Item 221).

Exports contracts and the core engine for in-sandbox output truncation,
diff distillation, and SQLite-backed fine-grained execution transaction ledgers.
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
