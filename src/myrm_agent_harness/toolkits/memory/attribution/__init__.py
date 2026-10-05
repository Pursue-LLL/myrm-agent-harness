"""Full-Lifecycle Memory Attribution and Explainable Traceability Matrix.

Tracks memory penetration across candidate recall, pruning/discard, prompt injection,
and output citation stages; provides graph projections, revocation audits, and
four-dimensional production health matrix evaluations.
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
