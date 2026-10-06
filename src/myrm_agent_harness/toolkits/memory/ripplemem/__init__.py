"""RippleMem sparse event graph and budgeted active recall controller package.

[INPUT]
- Domain models from .models.
- Extractor from .event_extractor.
- Graph store from .sparse_graph.
- Controller from .recall_controller.

[OUTPUT]
- Public exports for RippleMem architecture integration.

[POS]
Exports normalized event modeling, dual-edge sparse graph indexing,
and active recall controller engines for multi-session distributed evidence reasoning.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.ripplemem.event_extractor import (
    NormalizedEventExtractor,
)
from myrm_agent_harness.toolkits.memory.ripplemem.models import (
    GraphEdgeType,
    MissingSupportTarget,
    MultiHopProvenanceStep,
    MultiHopProvenanceTrace,
    NormalizedEventUnit,
    RippleRecallResult,
    RippleSpreadBudget,
    SparseEventEdge,
)
from myrm_agent_harness.toolkits.memory.ripplemem.recall_controller import (
    ActiveRecallController,
)
from myrm_agent_harness.toolkits.memory.ripplemem.sparse_graph import (
    DualEdgeSparseGraphStore,
)

__all__ = [
    "ActiveRecallController",
    "DualEdgeSparseGraphStore",
    "GraphEdgeType",
    "MissingSupportTarget",
    "MultiHopProvenanceStep",
    "MultiHopProvenanceTrace",
    "NormalizedEventExtractor",
    "NormalizedEventUnit",
    "RippleRecallResult",
    "RippleSpreadBudget",
    "SparseEventEdge",
]
