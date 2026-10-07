"""Types and models for redaction.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- MediaAttachmentKind: Supported multimodal media categories.
- DirectToolPolicyKind: Tool execution result delivery classification.
- MediaAttachment: Multimodal media attachment payload.
- RedactedToolResult: Scrubbed tool output representation for historical turns.
- HistoryMessageView: In-memory projected message representation for LLM context assembly.
- DegradationReport: Summary metrics of context degradation and payload scrubbing.

[POS]
Types and models for redaction.
"""

# ============================================================================
# Direct-Tool Redaction & Multimodal Degradation Data Contracts (Item 158)
# Strong typing contracts for direct-to-user tool payload scrubbing,
# cross-turn multimodal byte stripping, and sidecar question-aware captioning.
# ============================================================================

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class MediaAttachmentKind(str, Enum):
    """Supported multimodal media categories."""

    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    DOCUMENT = "document"


class DirectToolPolicyKind(str, Enum):
    """Tool execution result delivery classification."""

    DIRECT_TO_USER = "direct_to_user"  # Payloads delivered straight to user channel/UI
    STANDARD_TOOL = "standard_tool"  # Normal scratchpad/code execution results
    SIDE_EFFECT_DELIVERY = "side_effect_delivery"  # External webhook/file export actions


@dataclass(frozen=True, slots=True)
class MediaAttachment:
    """Multimodal media attachment payload."""

    attachment_id: str
    kind: MediaAttachmentKind
    mime_type: str
    file_name: str
    raw_bytes_base64: str | None = None
    caption: str | None = None
    token_estimate: int = 0


@dataclass(frozen=True, slots=True)
class RedactedToolResult:
    """Scrubbed tool output representation for historical turns."""

    tool_call_id: str
    tool_name: str
    is_redacted: bool
    final_content: str
    original_byte_size: int
    placeholder_text: str | None = None


@dataclass(frozen=True, slots=True)
class HistoryMessageView:
    """In-memory projected message representation for LLM context assembly."""

    role: str
    content: str
    turn_index: int
    is_current_turn: bool
    attachments: tuple[MediaAttachment, ...] = field(default_factory=tuple)
    tool_results: tuple[RedactedToolResult, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class DegradationReport:
    """Summary metrics of context degradation and payload scrubbing."""

    total_messages_processed: int
    tools_redacted_count: int
    media_degraded_count: int
    bytes_saved_estimate: int
    tokens_saved_estimate: int
