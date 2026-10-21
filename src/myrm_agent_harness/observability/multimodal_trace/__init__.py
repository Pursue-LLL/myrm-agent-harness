"""[INPUT] Multimodal media assets, trace spans, and 3-step inspector inputs.
[OUTPUT] Public facade exporting media reference abstractions and thread-safe multimodal trace manager.
[POS] myrm_agent_harness.observability.multimodal_trace

Exposes:
- Models: MediaModality, MediaVisibilityState, MediaReference, MultimodalMessagePart, MultimodalStepType, MultimodalTraceStep, MultimodalTraceRecord
- Manager: MultimodalTraceManager, get_default_multimodal_trace_manager
"""

from .manager import (
    MultimodalTraceManager,
    get_default_multimodal_trace_manager,
)
from .models import (
    MediaModality,
    MediaReference,
    MediaVisibilityState,
    MultimodalMessagePart,
    MultimodalStepType,
    MultimodalTraceRecord,
    MultimodalTraceStep,
)

__all__ = [
    "MediaModality",
    "MediaReference",
    "MediaVisibilityState",
    "MultimodalMessagePart",
    "MultimodalStepType",
    "MultimodalTraceRecord",
    "MultimodalTraceStep",
    "MultimodalTraceManager",
    "get_default_multimodal_trace_manager",
]
