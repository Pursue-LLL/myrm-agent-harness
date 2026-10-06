"""Multi-Gateway trust tiering, high-risk action interception, and signed Handoff Cards.

Prevents unauthorized execution on restricted gateways (e.g. mobile/voice) by generating
tamper-evident Handoff Cards for seamless resumption on trusted gateways (CLI/Desktop).
"""

from __future__ import annotations

import hashlib
import hmac
import time
import uuid
from typing import ClassVar

from myrm_agent_harness.runtime.context.multi_gateway_trust_types import (
    GatewayTrustTier,
    HandoffCard,
    HandoffCardStatus,
    HighRiskActionKind,
)


class MultiGatewayTrustGovernor:
    """Enforces trust tier boundaries across heterogeneous client gateways.

    High-risk mutations from restricted gateways are intercepted and wrapped into
    signed Handoff Cards destined for execution on trusted platforms.
    """

    # Actions permitted per gateway tier
    ALLOWED_ACTIONS_BY_TIER: ClassVar[dict[GatewayTrustTier, frozenset[HighRiskActionKind]]] = {
        GatewayTrustTier.CLI_TRUSTED: frozenset(HighRiskActionKind),
        GatewayTrustTier.DESKTOP_TRUSTED: frozenset(HighRiskActionKind),
        GatewayTrustTier.WEBUI_STANDARD: frozenset(
            {HighRiskActionKind.EXTERNAL_WRITE}
        ),
        GatewayTrustTier.MOBILE_RESTRICTED: frozenset(),
        GatewayTrustTier.VOICE_MINIMAL: frozenset(),
    }

    def __init__(self, hmac_secret_key: str = "myrm-trust-governor-default-key") -> None:
        self._secret_key = hmac_secret_key.encode("utf-8")
        self._card_store: dict[str, HandoffCard] = {}

    def is_action_permitted(
        self,
        gateway: GatewayTrustTier,
        action_kind: HighRiskActionKind,
    ) -> bool:
        """Check if the given gateway tier has direct clearance to run the action."""
        allowed = self.ALLOWED_ACTIONS_BY_TIER.get(gateway, frozenset())
        return action_kind in allowed

    def _generate_signature(
        self,
        handoff_id: str,
        session_id: str,
        action_kind: str,
        action_payload: str,
        created_at_utc: str,
    ) -> str:
        """Create HMAC-SHA256 signature to guarantee handoff payload authenticity."""
        raw_msg = (
            f"{handoff_id}|{session_id}|{action_kind}|{action_payload}|{created_at_utc}"
        )
        return hmac.new(self._secret_key, raw_msg.encode("utf-8"), hashlib.sha256).hexdigest()

    def intercept_and_create_handoff(
        self,
        source_gateway: GatewayTrustTier,
        action_kind: HighRiskActionKind,
        action_payload: str,
        session_id: str,
        explanation: str,
        target_gateway: GatewayTrustTier = GatewayTrustTier.DESKTOP_TRUSTED,
    ) -> HandoffCard:
        """Intercept a restricted action and package it into a signed HandoffCard."""
        handoff_id = f"card-{uuid.uuid4().hex[:12]}"
        created_at_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        signature = self._generate_signature(
            handoff_id=handoff_id,
            session_id=session_id,
            action_kind=action_kind.value,
            action_payload=action_payload,
            created_at_utc=created_at_utc,
        )

        card = HandoffCard(
            handoff_id=handoff_id,
            session_id=session_id,
            source_gateway=source_gateway,
            target_gateway=target_gateway,
            action_kind=action_kind,
            action_payload=action_payload,
            explanation=explanation,
            signature=signature,
            created_at_utc=created_at_utc,
            status=HandoffCardStatus.PENDING_APPROVAL,
        )

        self._card_store[handoff_id] = card
        return card

    def verify_and_approve_handoff(
        self,
        handoff_id: str,
        current_gateway: GatewayTrustTier,
    ) -> tuple[bool, str, HandoffCard | None]:
        """Verify signature and approve execution when loaded in a trusted gateway."""
        card = self._card_store.get(handoff_id)
        if not card:
            return False, f"Handoff card '{handoff_id}' not found.", None

        if card.status != HandoffCardStatus.PENDING_APPROVAL:
            return False, f"Card already in status: {card.status.value}", card

        # Verify gateway privileges
        if not self.is_action_permitted(current_gateway, card.action_kind):
            return (
                False,
                f"Current gateway '{current_gateway.value}' lacks permissions for '{card.action_kind.value}'.",
                card,
            )

        # Validate cryptographic signature
        expected_sig = self._generate_signature(
            handoff_id=card.handoff_id,
            session_id=card.session_id,
            action_kind=card.action_kind.value,
            action_payload=card.action_payload,
            created_at_utc=card.created_at_utc,
        )

        if not hmac.compare_digest(card.signature, expected_sig):
            return False, "Signature mismatch; handoff card may be tampered.", card

        # Update card status
        approved_card = HandoffCard(
            handoff_id=card.handoff_id,
            session_id=card.session_id,
            source_gateway=card.source_gateway,
            target_gateway=card.target_gateway,
            action_kind=card.action_kind,
            action_payload=card.action_payload,
            explanation=card.explanation,
            signature=card.signature,
            created_at_utc=card.created_at_utc,
            status=HandoffCardStatus.APPROVED_EXECUTED,
        )
        self._card_store[handoff_id] = approved_card
        return True, "Handoff approved and ready for execution.", approved_card
