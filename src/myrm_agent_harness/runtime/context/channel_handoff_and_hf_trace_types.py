"""Types for cross-platform channel handoff, HF trace export, and media pointers.

Defines schemas for channel handoffs, thread anchors, HuggingFace agent trace
records, and turn-scoped media pointer lifecycles.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- TargetChannelType: Supported interactive client channels.
- ChannelThreadKind: Specific platform thread anchoring strategy.
- ChannelThreadAnchorDescriptor: Descriptor of platform-native thread anchor.
- HandoffSessionEnvelope: Cryptographically anchored session handoff envelope.
- MediaPointerReference: Turn-scoped lightweight media pointer replacing raw large payloads.
- HFTraceStepRecord: Single step conforming to HuggingFace Agent Trace Viewer specification.

[POS]
Types for cross-platform channel handoff, HF trace export, and media pointers.
"""

from dataclasses import dataclass, field
from enum import StrEnum


class TargetChannelType(StrEnum):
    """Supported interactive client channels."""

    WEB_UI = "WEB_UI"
    CLI = "CLI"
    TELEGRAM = "TELEGRAM"
    DISCORD = "DISCORD"
    SLACK = "SLACK"
    FEISHU = "FEISHU"
    WECHAT = "WECHAT"


class ChannelThreadKind(StrEnum):
    """Specific platform thread anchoring strategy."""

    FORUM_TOPIC = "FORUM_TOPIC"  # Telegram Forum Topic
    AUTO_ARCHIVE_THREAD = "AUTO_ARCHIVE_THREAD"  # Discord thread
    ANCHOR_MESSAGE = "ANCHOR_MESSAGE"  # Slack thread parent
    TOPIC_CONTAINER = "TOPIC_CONTAINER"  # Feishu group topic
    DIRECT_CHANNEL = "DIRECT_CHANNEL"  # Fallback home channel


@dataclass(frozen=True)
class ChannelThreadAnchorDescriptor:
    """Descriptor of platform-native thread anchor."""

    channel_type: TargetChannelType
    thread_kind: ChannelThreadKind
    thread_identifier: str
    parent_message_id: str | None = None
    platform_metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class HandoffSessionEnvelope:
    """Cryptographically anchored session handoff envelope."""

    session_id: str
    source_channel: TargetChannelType
    target_channel: TargetChannelType
    thread_anchor: ChannelThreadAnchorDescriptor
    resumption_token: str
    state_fingerprint: str
    created_at: str
    context_turns_count: int


@dataclass(frozen=True)
class MediaPointerReference:
    """Turn-scoped lightweight media pointer replacing raw large payloads."""

    media_id: str
    mime_type: str
    byte_size: int
    local_cache_path: str
    semantic_caption: str
    turn_introduced: int

    def to_pointer_directive(self) -> str:
        """Format as a compact model-readable pointer tag."""
        return (
            f"[MediaPointer: id={self.media_id} "
            f"mime={self.mime_type} "
            f"caption='{self.semantic_caption}' "
            f"path='{self.local_cache_path}']"
        )


@dataclass(frozen=True)
class HFTraceStepRecord:
    """Single step conforming to HuggingFace Agent Trace Viewer specification."""

    step_number: int
    role: str
    thought: str | None = None
    action_tool: str | None = None
    action_input: dict[str, str] | None = None
    observation: str | None = None
    final_output: str | None = None
    duration_ms: float = 0.0
    timestamp: str = ""
