"""Agent mention dual-mode interaction types and communication contracts.

Defines the dual-mode mention semantics: read-only isolated context snapshots
vs. active peer-to-peer bidirectional communication channels.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- AgentMentionMode: Collaborative intent mode when mentioning a peer agent session.
- NormalizedAgentMention: Normalized @ mention token extracted from user prompt or UI picker.
- ReadOnlySnapshotBundle: Read-only context snapshot captured from a historical or parallel session.
- BidiChannelLink: Active bi-directional communication channel link between two peer sessions.
- PeerMessageFrame: Message frame exchanged over a bi-directional agent channel.
- MentionProcessingAudit: Diagnostic audit reporting outcomes of dual-mode mention processing.

[POS]
Agent mention dual-mode interaction types and communication contracts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class AgentMentionMode(StrEnum):
    """Collaborative intent mode when mentioning a peer agent session."""

    READ_ONLY = "read_only"  # Zero-side-effect context snapshot, peer agent is not alerted
    BIDIRECTIONAL = "bidirectional"  # Active peer-to-peer communication channel with live relay


@dataclass(frozen=True)
class NormalizedAgentMention:
    """Normalized @ mention token extracted from user prompt or UI picker."""

    target_session_id: str
    mode: AgentMentionMode
    mention_label: str = ""
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ReadOnlySnapshotBundle:
    """Read-only context snapshot captured from a historical or parallel session."""

    source_session_id: str
    target_session_id: str
    summary_markdown: str
    retained_messages_count: int
    captured_at: float
    workspace_path: str = ""


@dataclass(frozen=True)
class BidiChannelLink:
    """Active bi-directional communication channel link between two peer sessions."""

    channel_id: str
    session_a: str
    session_b: str
    ttl_seconds: float
    created_at: float
    expires_at: float
    is_active: bool = True


@dataclass(frozen=True)
class PeerMessageFrame:
    """Message frame exchanged over a bi-directional agent channel."""

    frame_id: str
    channel_id: str
    sender_session_id: str
    receiver_session_id: str
    payload: str
    timestamp: float
    acknowledged: bool = False


@dataclass(frozen=True)
class MentionProcessingAudit:
    """Diagnostic audit reporting outcomes of dual-mode mention processing."""

    total_mentions: int
    read_only_injected: int
    bidi_channels_linked: int
    bidi_channels_rejected: int
    captured_tokens_approx: int
