"""Package facade for multimodal redaction.

[INPUT]
-
  agent.context_management.multimodal_redaction.direct_tool_multimodal_degrader::DirectToolHistoryPlaceholderFilter,
  DirectToolMultimodalDegradationEngine, MultimodalAttachmentDegrader, QuestionAwareSidecarCaptioner (POS:
  Unified pipeline for direct-tool scrubbing and multimodal attachment degradation.)
- agent.context_management.multimodal_redaction.redaction_types::DegradationReport, DirectToolPolicyKind,
  HistoryMessageView, MediaAttachment, MediaAttachmentKind, RedactedToolResult (POS: Types and models for
  redaction.)

[OUTPUT]
- Re-exports: DegradationReport, DirectToolHistoryPlaceholderFilter, DirectToolMultimodalDegradationEngine,
  DirectToolPolicyKind, HistoryMessageView, MediaAttachment, MediaAttachmentKind,
  MultimodalAttachmentDegrader, QuestionAwareSidecarCaptioner, RedactedToolResult

[POS]
Package facade for multimodal redaction.
"""

# ============================================================================
# Multimodal Redaction & Direct-Tool Degradation Package (Item 158)
# ============================================================================

from .direct_tool_multimodal_degrader import (
    DirectToolHistoryPlaceholderFilter,
    DirectToolMultimodalDegradationEngine,
    MultimodalAttachmentDegrader,
    QuestionAwareSidecarCaptioner,
)
from .redaction_types import (
    DegradationReport,
    DirectToolPolicyKind,
    HistoryMessageView,
    MediaAttachment,
    MediaAttachmentKind,
    RedactedToolResult,
)

__all__ = [
    "DegradationReport",
    "DirectToolHistoryPlaceholderFilter",
    "DirectToolMultimodalDegradationEngine",
    "DirectToolPolicyKind",
    "HistoryMessageView",
    "MediaAttachment",
    "MediaAttachmentKind",
    "MultimodalAttachmentDegrader",
    "QuestionAwareSidecarCaptioner",
    "RedactedToolResult",
]
