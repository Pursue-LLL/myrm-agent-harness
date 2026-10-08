"""Webhook Toolset Demoter and Admin Escalation Gatekeeper.

[INPUT]
- Tool names, tool arguments, OriginTaint metadata, approval cards.

[OUTPUT]
- Filtered safe toolsets for untrusted contexts.
- Execution validation verdicts and AdminApprovalCards.
- DemotedToolAccessDeniedError raised when dangerous executions lack human approval.

[POS]
- Harness core security module inspired by Hermes Agent message gateway.
- Enforces runtime tool demotion and human-in-the-loop escalation for external untrusted webhooks.
"""

from __future__ import annotations

import threading
import time
import uuid

from myrm_agent_harness.core.security.webhook_guard.types import (
    AdminApprovalCard,
    ApprovalCardStatus,
    DemotedToolAccessDeniedError,
    DemotionPolicy,
    OriginTaint,
)


class WebhookToolsetDemoter:
    """Thread-safe controller that demotes toolsets for tainted sessions and manages admin approval cards."""

    def __init__(self, policy: DemotionPolicy | None = None) -> None:
        self._policy = policy or DemotionPolicy()
        self._cards: dict[str, AdminApprovalCard] = {}
        self._lock = threading.Lock()

    @property
    def policy(self) -> DemotionPolicy:
        """Access current demotion policy."""
        return self._policy

    def filter_available_tools(
        self,
        all_tools: list[str],
        taint: OriginTaint | None,
    ) -> list[str]:
        """Filter list of tools, stripping high-risk tools if origin content is untrusted."""
        if not taint or not taint.is_untrusted_external_content:
            return list(all_tools)

        # Retain only recognized safe tools and exclude explicitly forbidden high-risk tools
        safe_set = self._policy.safe_read_only_tools
        forbidden_set = self._policy.forbidden_high_risk_tools

        return [t for t in all_tools if t in safe_set and t not in forbidden_set]

    def evaluate_execution(
        self,
        task_id: str,
        tool_name: str,
        tool_args: dict[str, str | int | float | bool | list[str]],
        taint: OriginTaint | None,
    ) -> tuple[bool, AdminApprovalCard | None]:
        """Evaluate if tool invocation is permitted.

        Raises:
            DemotedToolAccessDeniedError: If dangerous tool is called under untrusted taint without approval.
        """
        # Untainted context -> unrestricted execution
        if not taint or not taint.is_untrusted_external_content:
            return True, None

        # Safe read-only tool in tainted context -> permitted
        if tool_name in self._policy.safe_read_only_tools and tool_name not in self._policy.forbidden_high_risk_tools:
            return True, None

        # Check if an existing approved card permits this invocation
        with self._lock:
            for card in self._cards.values():
                if (
                    card.task_id == task_id
                    and card.requested_tool == tool_name
                    and card.status == ApprovalCardStatus.APPROVED
                    and time.time() <= card.expires_at
                ):
                    return True, card

        # Forbidden/demoted tool without approved card -> generate approval card and block
        card_id = f"card_{uuid.uuid4().hex[:10]}"
        risk_reason = (
            f"Tool '{tool_name}' performs destructive/elevated actions, blocked due to untrusted "
            f"input origin '{taint.origin_source}' by '{taint.sender_identity}'."
        )
        new_card = AdminApprovalCard(
            card_id=card_id,
            task_id=task_id,
            origin_source=taint.origin_source,
            requested_tool=tool_name,
            tool_arguments=tool_args,
            risk_reason=risk_reason,
            status=ApprovalCardStatus.PENDING,
        )

        with self._lock:
            self._cards[card_id] = new_card

        raise DemotedToolAccessDeniedError(
            tool_name=tool_name,
            origin_source=taint.origin_source,
            card_id=card_id,
        )

    def approve_card(self, card_id: str) -> AdminApprovalCard:
        """Approve an interactive admin escalation card."""
        with self._lock:
            card = self._cards.get(card_id)
            if not card:
                raise KeyError(f"Approval card '{card_id}' not found")
            if time.time() > card.expires_at:
                expired_card = AdminApprovalCard(
                    card_id=card.card_id,
                    task_id=card.task_id,
                    origin_source=card.origin_source,
                    requested_tool=card.requested_tool,
                    tool_arguments=card.tool_arguments,
                    risk_reason=card.risk_reason,
                    status=ApprovalCardStatus.EXPIRED,
                    created_at=card.created_at,
                    expires_at=card.expires_at,
                )
                self._cards[card_id] = expired_card
                raise ValueError("Approval card has expired")

            approved_card = AdminApprovalCard(
                card_id=card.card_id,
                task_id=card.task_id,
                origin_source=card.origin_source,
                requested_tool=card.requested_tool,
                tool_arguments=card.tool_arguments,
                risk_reason=card.risk_reason,
                status=ApprovalCardStatus.APPROVED,
                created_at=card.created_at,
                expires_at=card.expires_at,
            )
            self._cards[card_id] = approved_card
            return approved_card

    def reject_card(self, card_id: str) -> AdminApprovalCard:
        """Reject and cancel an interactive admin escalation card."""
        with self._lock:
            card = self._cards.get(card_id)
            if not card:
                raise KeyError(f"Approval card '{card_id}' not found")

            rejected_card = AdminApprovalCard(
                card_id=card.card_id,
                task_id=card.task_id,
                origin_source=card.origin_source,
                requested_tool=card.requested_tool,
                tool_arguments=card.tool_arguments,
                risk_reason=card.risk_reason,
                status=ApprovalCardStatus.REJECTED,
                created_at=card.created_at,
                expires_at=card.expires_at,
            )
            self._cards[card_id] = rejected_card
            return rejected_card

    def get_card(self, card_id: str) -> AdminApprovalCard | None:
        """Retrieve an approval card by ID."""
        with self._lock:
            return self._cards.get(card_id)

    def list_cards(self, status: ApprovalCardStatus | None = None) -> list[AdminApprovalCard]:
        """List all approval cards, optionally filtered by lifecycle status."""
        with self._lock:
            cards = list(self._cards.values())
        if status:
            return [c for c in cards if c.status == status]
        return cards
