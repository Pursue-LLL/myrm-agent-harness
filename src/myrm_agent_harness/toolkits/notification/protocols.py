"""Notification sender protocol.

Defines the contract that the application layer must implement to enable
the channel_notify_tool. The framework layer only defines the interface;
concrete channel routing (Telegram, Slack, etc.) lives in the server layer.

[INPUT]
- (none — pure protocol definition)

[OUTPUT]
- NotificationSender: Protocol for sending notifications to external channels.

[POS]
Protocol for cross-channel notification delivery. Framework-layer contract;
business layer provides the concrete implementation.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .types import NotifyResult, NotifyTarget


@runtime_checkable
class NotificationSender(Protocol):
    """Sends a notification message to a configured external channel.

    The application layer implements this by routing through its channel
    infrastructure (e.g. MessageBus, ChannelGateway). The framework only
    cares about the contract.
    """

    async def send(
        self,
        target: NotifyTarget,
        body: str,
    ) -> NotifyResult:
        """Deliver a notification to the specified target.

        Args:
            target: Resolved notification target (channel + recipient).
            body: Message content to send.

        Returns:
            NotifyResult indicating success or failure with detail.
        """
        ...

    async def list_available_targets(self) -> list[NotifyTarget]:
        """Return all configured notification targets for the current agent.

        Used by the tool to provide helpful error messages when the agent
        specifies an invalid target.
        """
        ...
