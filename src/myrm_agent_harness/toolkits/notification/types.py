"""Notification toolkit data types.

[INPUT]
- (none — pure data definitions)

[OUTPUT]
- NotifyTarget: Channel + recipient target for notification delivery.
- NotifyToolConfig: Configuration for the channel_notify_tool.
- NotifyResult: Result of a notification send attempt.

[POS]
Data types for the notification toolkit. Shared between protocol, tool, and
application layer implementations.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class NotifyTarget:
    """A configured notification target (channel + recipient)."""

    channel: str
    """Channel identifier (e.g. 'telegram', 'slack')."""

    recipient_id: str
    """Platform-specific recipient ID (e.g. chat_id, channel_id)."""

    label: str = ""
    """Human-readable label for display (e.g. 'My Telegram', '#devops-alerts')."""


@dataclass(frozen=True, slots=True)
class NotifyToolConfig:
    """Configuration for the channel_notify_tool.

    Passed from the application layer when constructing the tool.
    """

    allowed_targets: tuple[NotifyTarget, ...] = ()
    """Whitelist of targets the agent is allowed to send to."""

    rate_limit_per_session: int = 10
    """Maximum number of notifications per agent session (prevents spam)."""

    max_body_length: int = 4000
    """Maximum message body length in characters."""


@dataclass(frozen=True, slots=True)
class NotifyResult:
    """Result of a notification send attempt."""

    success: bool
    """Whether the notification was delivered successfully."""

    channel: str = ""
    """Channel that was used for delivery."""

    error: str = ""
    """Error message if delivery failed."""

    message_id: str = ""
    """Platform message ID if available (for tracking)."""


@dataclass(slots=True)
class NotifySessionState:
    """Per-session state for rate limiting."""

    send_count: int = 0
    """Number of notifications sent in this session."""

    targets_used: list[str] = field(default_factory=list)
    """Targets that have been sent to (for audit)."""
