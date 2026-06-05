"""Channel notify tool — Agent-callable tool for cross-channel notifications.

Enables the agent to send notifications to user-configured external channels
(Telegram, Slack, etc.) during a conversation. Security is enforced via:
1. Whitelist: only targets explicitly configured by the user are reachable.
2. Rate limit: per-session cap prevents spam.
3. Content safety: body passes through the existing guardrail pipeline.

[INPUT]
- .protocols::NotificationSender (POS: Protocol for notification delivery)
- .types::NotifyToolConfig, NotifySessionState (POS: Config and state types)

[OUTPUT]
- create_channel_notify_tool: Factory that creates the LangChain tool.

[POS]
Agent-callable channel notification tool. Framework-layer implementation;
the concrete sender is injected by the application layer.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from langchain_core.tools.convert import tool
from pydantic import BaseModel, Field

from .types import NotifySessionState, NotifyTarget, NotifyToolConfig

if TYPE_CHECKING:
    from .protocols import NotificationSender

logger = logging.getLogger(__name__)


class _NotifyInput(BaseModel):
    """Input schema for channel_notify_tool."""

    channel: str = Field(
        description=(
            "Target channel name (e.g. 'telegram', 'slack'). If only one target is configured, this can be omitted."
        ),
        default="",
    )
    target: str = Field(
        description=(
            "Optional recipient ID within the channel. "
            "When omitted, uses the default/only configured target for that channel."
        ),
        default="",
    )
    body: str = Field(
        description="The notification message content to send.",
    )


def create_channel_notify_tool(
    sender: NotificationSender,
    config: NotifyToolConfig,
) -> object:
    """Create a channel_notify_tool bound to the given sender and config.

    Args:
        sender: Application-layer notification sender implementation.
        config: Tool configuration (allowed targets, rate limits).

    Returns:
        A LangChain tool instance ready to be added to the agent's tool list.
    """
    session_state = NotifySessionState()

    @tool("channel_notify_tool", args_schema=_NotifyInput)
    async def channel_notify_tool(
        channel: str = "",
        target: str = "",
        body: str = "",
    ) -> str:
        """Send a notification message to a configured external channel.

        Use this tool when:
        - The user asks to be notified on another platform (e.g. "notify me on Telegram when done")
        - You need to send an alert or result to a specific channel
        - Cross-channel delivery is requested (e.g. "send this summary to Slack")

        The tool only works for channels that the user has explicitly configured
        in their agent's notification settings.
        """
        if not body.strip():
            return "Error: notification body cannot be empty."

        if not config.allowed_targets:
            return (
                "Error: no notification targets configured for this agent. "
                "The user needs to configure notification channels in the agent settings."
            )

        if session_state.send_count >= config.rate_limit_per_session:
            return (
                f"Error: notification rate limit reached "
                f"({config.rate_limit_per_session} per session). "
                f"Cannot send more notifications in this session."
            )

        if len(body) > config.max_body_length:
            body_truncated = body[: config.max_body_length] + "\n\n[...truncated]"
        else:
            body_truncated = body

        resolved_target = _resolve_target(channel, target, config.allowed_targets)
        if resolved_target is None:
            available = ", ".join(
                f"{t.channel}:{t.recipient_id}" + (f" ({t.label})" if t.label else "") for t in config.allowed_targets
            )
            return f"Error: target not found or not allowed. Available targets: [{available}]"

        result = await sender.send(resolved_target, body_truncated)

        session_state.send_count += 1
        session_state.targets_used.append(f"{resolved_target.channel}:{resolved_target.recipient_id}")

        if result.success:
            label = resolved_target.label or resolved_target.recipient_id
            return f"Notification sent successfully to {resolved_target.channel} ({label})."
        return f"Error: failed to send notification — {result.error}"

    return channel_notify_tool


def _resolve_target(
    channel: str,
    target: str,
    allowed: tuple[NotifyTarget, ...],
) -> NotifyTarget | None:
    """Resolve user-provided channel/target to an allowed NotifyTarget.

    Resolution strategy (mirrors zeroclaw's multi-fallback approach):
    1. Exact match: channel + target both match.
    2. Channel-only: channel matches, target omitted → use first match for that channel.
    3. Single-target: only one target configured → use it regardless of input.
    """
    if not allowed:
        return None

    # Single target shortcut: if only one target exists, use it
    if len(allowed) == 1 and not channel and not target:
        return allowed[0]

    # Exact match
    if channel and target:
        for t in allowed:
            if t.channel == channel and t.recipient_id == target:
                return t
        return None

    # Channel-only match
    if channel:
        for t in allowed:
            if t.channel == channel:
                return t
        # Try case-insensitive
        channel_lower = channel.lower()
        for t in allowed:
            if t.channel.lower() == channel_lower:
                return t
        return None

    # No channel specified but only one target
    if len(allowed) == 1:
        return allowed[0]

    # Target-only match (label or recipient_id)
    if target:
        for t in allowed:
            if t.recipient_id == target or t.label == target:
                return t

    return None
