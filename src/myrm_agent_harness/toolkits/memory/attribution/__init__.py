"""Full-Lifecycle Memory Attribution and Explainable Traceability Matrix.

Tracks memory penetration across candidate recall, pruning/discard, prompt injection,
and output citation stages; provides graph projections, revocation audits, and
four-dimensional production health matrix evaluations.

[INPUT]
- toolkits.memory.attribution.matrix::AttributionHealthMatrixEvaluator (POS: Attribution Health Matrix
  Evaluator computing production governance metrics.)
- toolkits.memory.attribution.models::AttributionGraphEdge, AttributionGraphNode, AttributionGraphPayload,
  CandidateRecallItem, DiscardedRecallItem, FilterDiscardReason, FourDimensionHealthReport,
  InjectedContextItem, +2 more (POS: Data models for Full-Lifecycle Memory Attribution and Explainable
  Traceability Matrix.)
- toolkits.memory.attribution.tracer::MemoryLifecycleTracer (POS: Memory Lifecycle Tracer documenting
  single-trace attribution flows.)

[OUTPUT]
- Package facade re-exporting 12 public names: AttributionGraphEdge, AttributionGraphNode,
  AttributionGraphPayload, AttributionHealthMatrixEvaluator, CandidateRecallItem, DiscardedRecallItem,
  FilterDiscardReason, FourDimensionHealthReport, InjectedContextItem, MemoryAttributionTrace,
  MemoryLifecycleTracer, ModelCitationItem

[POS]
Full-Lifecycle Memory Attribution and Explainable Traceability Matrix.
"""

from .matrix import AttributionHealthMatrixEvaluator
from .models import (
    AttributionGraphEdge,
    AttributionGraphNode,
    AttributionGraphPayload,
    CandidateRecallItem,
    DiscardedRecallItem,
    FilterDiscardReason,
    FourDimensionHealthReport,
    InjectedContextItem,
    MemoryAttributionTrace,
    ModelCitationItem,
)
from .tracer import MemoryLifecycleTracer

__all__ = [
    "AttributionGraphEdge",
    "AttributionGraphNode",
    "AttributionGraphPayload",
    "AttributionHealthMatrixEvaluator",
    "CandidateRecallItem",
    "DiscardedRecallItem",
    "FilterDiscardReason",
    "FourDimensionHealthReport",
    "InjectedContextItem",
    "MemoryAttributionTrace",
    "MemoryLifecycleTracer",
    "ModelCitationItem",
]
