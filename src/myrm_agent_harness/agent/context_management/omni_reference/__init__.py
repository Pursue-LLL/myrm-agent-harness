"""[INPUT]
- .slice_extractor::OmniReferenceExtractor
- .slice_extractor::ReferenceDimension
- .slice_extractor::ReferenceTarget
- .slice_extractor::ContextSlice
- .slice_extractor::format_omni_context_slices

[OUTPUT]
- Public re-exports for harness omni_reference package

[POS]
Facade for myrm_agent_harness.agent.context_management.omni_reference.
"""

from myrm_agent_harness.agent.context_management.omni_reference.slice_extractor import (
    ContextSlice,
    OmniReferenceExtractor,
    ReferenceDimension,
    ReferenceTarget,
    format_omni_context_slices,
)

__all__ = [
    "OmniReferenceExtractor",
    "ReferenceDimension",
    "ReferenceTarget",
    "ContextSlice",
    "format_omni_context_slices",
]
