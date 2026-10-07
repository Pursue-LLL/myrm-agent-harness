"""Dual-Track Fact Decision and Verbatim Evidence Tracer Engine.

Decouples instant deterministic state decisions (compact KV injection)
from in-depth historical retrospective evidence audits (lazy verbatim RAG expansion).

[INPUT]
- toolkits.memory.dual_track.models::DualTrackAssembly, EvidenceExpansionReport, FactDecisionEntry,
  VerbatimEvidenceSlice (POS: Data models for Dual-Track Fact Decision and Verbatim Evidence Tracer Engine.)
- toolkits.memory.dual_track.tracer::DualTrackDecisionTracer (POS: Dual-Track Decision Tracer engine
  decoupling high-privilege state facts and verbatim evidence.)

[OUTPUT]
- Package facade re-exporting 5 public names: DualTrackAssembly, DualTrackDecisionTracer,
  EvidenceExpansionReport, FactDecisionEntry, VerbatimEvidenceSlice

[POS]
Dual-Track Fact Decision and Verbatim Evidence Tracer Engine.
"""

from .models import (
    DualTrackAssembly,
    EvidenceExpansionReport,
    FactDecisionEntry,
    VerbatimEvidenceSlice,
)
from .tracer import DualTrackDecisionTracer

__all__ = [
    "DualTrackAssembly",
    "DualTrackDecisionTracer",
    "EvidenceExpansionReport",
    "FactDecisionEntry",
    "VerbatimEvidenceSlice",
]
