"""Notification toolkit — Agent-callable cross-channel notification delivery.

Protocol-first design: the framework defines the tool logic, rate limiting,
and security constraints. The concrete notification sender is injected by
the application layer (e.g. via ChannelGateway in myrm-agent-server).

Provides:
- NotificationSender: Protocol for the application layer to implement.
- NotifyToolConfig: Configuration dataclass for the tool.
- NotifyTarget: Channel + recipient target definition.
- NotifyResult: Result of a notification send attempt.
- create_channel_notify_tool: Factory that creates the agent-callable tool.

[INPUT]
- notification.protocols::NotificationSender (POS: send contract)
- notification.types (POS: data models)
- notification.tool::create_channel_notify_tool (POS: tool factory)

[OUTPUT]
- Public API for the notification toolkit.

[POS]
Notification toolkit entry point. Enables agents to send messages to external
channels (Telegram, Slack, etc.) with built-in security and rate limiting.
"""

from .protocols import NotificationSender
from .tool import create_channel_notify_tool
from .types import NotifyResult, NotifySessionState, NotifyTarget, NotifyToolConfig

__all__ = [
    "NotificationSender",
    "NotifyResult",
    "NotifySessionState",
    "NotifyTarget",
    "NotifyToolConfig",
    "create_channel_notify_tool",
]
