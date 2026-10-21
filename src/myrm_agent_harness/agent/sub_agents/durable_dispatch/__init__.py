"""[INPUT] None.
[OUTPUT] Facade exports for Hermes Fabric durable remote dispatch subsystem.
[POS] Public API package root for durable_dispatch.
"""

from .engine import (
    MAX_SINGLE_EVIDENCE_BYTES,
    MAX_TOTAL_EVIDENCE_BYTES,
    DurableRemoteDispatchEngine,
)
from .journal import DurableDispatchJournal
from .types import (
    DispatchJournalEntry,
    DispatchReceipt,
    EvidenceItem,
    JournalEntryType,
    RecoveryPlan,
    WorkContract,
)

__all__ = [
    "DurableRemoteDispatchEngine",
    "DurableDispatchJournal",
    "DispatchJournalEntry",
    "DispatchReceipt",
    "EvidenceItem",
    "JournalEntryType",
    "RecoveryPlan",
    "WorkContract",
    "MAX_SINGLE_EVIDENCE_BYTES",
    "MAX_TOTAL_EVIDENCE_BYTES",
]
