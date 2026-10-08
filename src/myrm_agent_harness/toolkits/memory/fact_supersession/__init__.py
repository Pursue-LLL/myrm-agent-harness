"""Package facade for fact supersession.

[INPUT]
- toolkits.memory.fact_supersession.contradiction_quarantine::ContradictionQuarantineGate (POS: Gate
  evaluating factual contradictions and routing low-confidence candidates into quarantine.)
- toolkits.memory.fact_supersession.dialectic_retriever::DialecticRecallProjector (POS: Projector augmenting
  recalled facts with their historical supersession lineage for explainability.)
- toolkits.memory.fact_supersession.models::ContradictionQuarantineItem, DialecticRecallProjection,
  TemporalFactRecord, TemporalFactStatus (POS: Types and models for fact supersession.)
- toolkits.memory.fact_supersession.supersession_chain::FactSupersessionChainEngine (POS: Engine managing fact
  lifecycle, explicit supersession chains, and valid-time interval queries.)

[OUTPUT]
- Re-exports: ContradictionQuarantineGate, ContradictionQuarantineItem, DialecticRecallProjection,
  DialecticRecallProjector, FactSupersessionChainEngine, TemporalFactRecord, TemporalFactStatus

[POS]
Package facade for fact supersession.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.fact_supersession.contradiction_quarantine import (
    ContradictionQuarantineGate,
)
from myrm_agent_harness.toolkits.memory.fact_supersession.dialectic_retriever import (
    DialecticRecallProjector,
)
from myrm_agent_harness.toolkits.memory.fact_supersession.models import (
    ContradictionQuarantineItem,
    DialecticRecallProjection,
    TemporalFactRecord,
    TemporalFactStatus,
)
from myrm_agent_harness.toolkits.memory.fact_supersession.supersession_chain import (
    FactSupersessionChainEngine,
)

__all__ = [
    "ContradictionQuarantineGate",
    "ContradictionQuarantineItem",
    "DialecticRecallProjection",
    "DialecticRecallProjector",
    "FactSupersessionChainEngine",
    "TemporalFactRecord",
    "TemporalFactStatus",
]
