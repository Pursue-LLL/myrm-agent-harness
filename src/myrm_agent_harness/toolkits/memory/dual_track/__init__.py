"""Dual-Track Fact Decision and Verbatim Evidence Tracer Engine.

Decouples instant deterministic state decisions (compact KV injection)
from in-depth historical retrospective evidence audits (lazy verbatim RAG expansion).
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
