"""Interactive approval webhook relay for multi-channel external notifications.

[POS] src/myrm_agent_harness/core/security/headless_interactive_approval/webhook_relay.py
[INPUT] myrm_agent_harness.core.security.headless_interactive_approval.types
[OUTPUT] InteractiveApprovalWebhookRelay
"""

from __future__ import annotations

import logging
from typing import Final

from myrm_agent_harness.core.security.headless_interactive_approval.types import (
    ApprovalHoldTicket,
    WebhookRelayPayload,
)

logger: Final[logging.Logger] = logging.getLogger(__name__)


class InteractiveApprovalWebhookRelay:
    """Relay builder formatting approval notifications for external messenger/push channels."""

    def __init__(self) -> None:
        # endpoint_name -> webhook_url
        self._endpoints: dict[str, str] = {}

    def register_endpoint(self, name: str, url: str) -> None:
        """Register an outbound webhook destination (e.g. 'telegram_secops', 'feishu_bot')."""
        self._endpoints[name] = url
        logger.info("Registered interactive approval webhook endpoint '%s'", name)

    def remove_endpoint(self, name: str) -> bool:
        """Remove a webhook endpoint."""
        return self._endpoints.pop(name, None) is not None

    def list_endpoints(self) -> dict[str, str]:
        """Return all active webhook endpoints."""
        return dict(self._endpoints)

    @staticmethod
    def build_payload(
        ticket: ApprovalHoldTicket,
        custom_metadata: dict[str, str] | None = None,
    ) -> WebhookRelayPayload:
        """Construct a standardized relay payload for external notification dispatchers."""
        remaining_seconds = max(0, int(ticket.expires_at - ticket.created_at))

        return WebhookRelayPayload(
            tx_id=ticket.tx_id,
            session_id=ticket.session_id,
            tool_name=ticket.action.tool_name,
            command_or_target=ticket.action.command_or_target,
            risk_level=ticket.action.risk_level,
            approval_shortlink=ticket.shortlink_url,
            expires_in_seconds=remaining_seconds,
            custom_metadata=custom_metadata or {},
        )

    @staticmethod
    def format_markdown_card(ticket: ApprovalHoldTicket) -> str:
        """Render a readable Markdown notification card suitable for Telegram or Feishu."""
        return (
            f"### 🛡️ Agent Security Approval Request\n\n"
            f"- **Transaction**: `{ticket.tx_id}`\n"
            f"- **Tool**: `{ticket.action.tool_name}`\n"
            f"- **Risk Tier**: **{ticket.action.risk_level}**\n"
            f"- **Target/Command**: `{ticket.action.command_or_target}`\n"
            f"- **Justification**: {ticket.action.justification}\n\n"
            f"👉 [**Click here to Authorize / Deny Action**]({ticket.shortlink_url})"
        )
