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
