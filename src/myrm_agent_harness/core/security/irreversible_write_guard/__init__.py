"""Pre-Flight Irreversible Write Interception and Emergency Kill Switch Module.

Provides pre-execution suspension, explosion radius review cards, and emergency abort
for tools performing irreversible external write operations (email, git push, payments, etc.).
"""

from __future__ import annotations

from .blast_radius_builder import BlastRadiusBuilder
from .contract_registry import (
    IrreversibleWriteContractRegistry,
)
from .kill_switch_guard import PreFlightIrreversibleWriteGuard
from .types import (
    BlastRadiusCard,
    EmergencyKillResult,
    InterceptionStatus,
    IrreversibleWriteContract,
    IrreversibleWriteIntent,
    RiskLevel,
    WriteDomain,
)

__all__ = [
    "BlastRadiusBuilder",
    "BlastRadiusCard",
    "EmergencyKillResult",
    "InterceptionStatus",
    "IrreversibleWriteContract",
    "IrreversibleWriteContractRegistry",
    "IrreversibleWriteIntent",
    "PreFlightIrreversibleWriteGuard",
    "RiskLevel",
    "WriteDomain",
]
