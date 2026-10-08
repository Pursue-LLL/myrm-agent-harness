"""Public contracts and facade for deterministic runtime state ledger and cache-friendly tail injection.

[INPUT]
- None (Facade exports).

[OUTPUT]
- DeterministicLedgerCompiler: Pure deterministic calculator producing structured state snapshots.
- DeterministicRuntimeStateLedgerInjectionSuite: Unified top-level facade.
- LedgerInjectionResult: Outcome holding rendered tag and token statistics.
- LedgerUpdatePolicy: Strategy governing replace vs append modes.
- QuotaConstraint: Finite quota constraint counter.
- RuntimeLedgerConfig: Settings controlling tag name and budgets.
- RuntimeStateSnapshot: Deterministically compiled status snapshot.
- TailLedgerInjector: Serializer and context tail injector.
- TodoProgress: Task checklist item tracking progression.

[POS]
Modular subpackage in agent/context_management implementing the <agent_status> dashboard paradigm.
"""

from __future__ import annotations

from .deterministic_ledger_compiler import DeterministicLedgerCompiler
from .deterministic_runtime_state_ledger_suite import (
    DeterministicRuntimeStateLedgerInjectionSuite,
)
from .runtime_ledger_types import (
    LedgerInjectionResult,
    LedgerUpdatePolicy,
    QuotaConstraint,
    RuntimeLedgerConfig,
    RuntimeStateSnapshot,
    TodoProgress,
)
from .tail_ledger_injector import TailLedgerInjector

__all__ = [
    "DeterministicLedgerCompiler",
    "DeterministicRuntimeStateLedgerInjectionSuite",
    "LedgerInjectionResult",
    "LedgerUpdatePolicy",
    "QuotaConstraint",
    "RuntimeLedgerConfig",
    "RuntimeStateSnapshot",
    "TailLedgerInjector",
    "TodoProgress",
]
