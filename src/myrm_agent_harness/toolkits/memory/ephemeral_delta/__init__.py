# [POS]: src/myrm_agent_harness/toolkits/memory/ephemeral_delta/__init__.py
# [INPUT]: models.py, delta_store.py, tail_injector.py, reconciler.py
# [OUTPUT]: Public facade for EphemeralDeltaMemorySuite

"""Prompt-cache-preserving ephemeral session delta memory suite.

Decouples SystemPrompt frozen snapshot preservation from real-time turn corrections.
Deltas are held in a transient buffer and injected safely at the Human tail.

[INPUT]
- toolkits.memory.ephemeral_delta.delta_store::EphemeralDeltaStore (POS: In-memory, session-scoped transient
  buffer for prompt-cache-preserving deltas.)
- toolkits.memory.ephemeral_delta.models::DeltaActionKind, EphemeralDeltaBufferSnapshot, EphemeralDeltaItem,
  ReconciliationBatchReport (POS: Types and models for ephemeral delta.)
- toolkits.memory.ephemeral_delta.reconciler::EphemeralDeltaReconciler (POS: Asynchronous reconciliation loop
  for persisting transient session deltas.)
- toolkits.memory.ephemeral_delta.tail_injector::HumanTailDeltaInjector (POS: Injects active ephemeral session
  deltas at the tail of the final HumanMessage.)

[OUTPUT]
- Re-exports: DeltaActionKind, EphemeralDeltaBufferSnapshot, EphemeralDeltaItem, EphemeralDeltaReconciler,
  EphemeralDeltaStore, HumanTailDeltaInjector, ReconciliationBatchReport

[POS]
Prompt-cache-preserving ephemeral session delta memory suite.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.ephemeral_delta.delta_store import (
    EphemeralDeltaStore,
)
from myrm_agent_harness.toolkits.memory.ephemeral_delta.models import (
    DeltaActionKind,
    EphemeralDeltaBufferSnapshot,
    EphemeralDeltaItem,
    ReconciliationBatchReport,
)
from myrm_agent_harness.toolkits.memory.ephemeral_delta.reconciler import (
    EphemeralDeltaReconciler,
)
from myrm_agent_harness.toolkits.memory.ephemeral_delta.tail_injector import (
    HumanTailDeltaInjector,
)

__all__ = [
    "DeltaActionKind",
    "EphemeralDeltaBufferSnapshot",
    "EphemeralDeltaItem",
    "EphemeralDeltaReconciler",
    "EphemeralDeltaStore",
    "HumanTailDeltaInjector",
    "ReconciliationBatchReport",
]
