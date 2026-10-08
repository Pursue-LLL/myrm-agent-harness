"""
[POS] src/myrm_agent_harness/core/security/confidential_payment_sandbox/virtual_card_proxy.py
[INPUT] time, uuid, types
[OUTPUT] SingleUseVirtualCardProxy
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import logging
import random
import time
import uuid

from .types import (
    SingleUseVirtualCard,
    VirtualCardPaymentReceipt,
    VirtualCardPaymentRequest,
    VirtualCardStatus,
)

logger = logging.getLogger(__name__)


class SingleUseVirtualCardProxy:
    """Manages blind credential tokenization, disposable single-use virtual cards, and payment controls."""

    def __init__(self, hitl_threshold_default: float = 50.0) -> None:
        self._cards: dict[str, SingleUseVirtualCard] = {}
        self._hitl_threshold_default = hitl_threshold_default

    def issue_card(
        self,
        spending_limit: float,
        currency: str = "USD",
        validity_seconds: float = 3600.0,
        hitl_threshold: float | None = None,
        current_time: float | None = None,
    ) -> SingleUseVirtualCard:
        """Issue a blind disposable virtual card token."""
        now = time.time() if current_time is None else current_time
        threshold = self._hitl_threshold_default if hitl_threshold is None else hitl_threshold

        card_token = f"vcard-tok-{uuid.uuid4().hex[:12]}"
        random_suffix = f"{random.randint(1000, 9999)}"
        masked_number = f"****-****-****-{random_suffix}"

        requires_hitl = spending_limit >= threshold

        card = SingleUseVirtualCard(
            card_token=card_token,
            masked_card_number=masked_number,
            currency=currency.upper(),
            spending_limit=spending_limit,
            amount_spent=0.0,
            status=VirtualCardStatus.ACTIVE,
            created_at=now,
            expires_at=now + validity_seconds,
            requires_hitl=requires_hitl,
        )
        self._cards[card_token] = card
        logger.info(
            "Issued disposable virtual card %s (limit: %s %s, requires_hitl: %s)",
            card_token,
            spending_limit,
            currency,
            requires_hitl,
        )
        return card

    def get_card(self, card_token: str) -> SingleUseVirtualCard | None:
        """Retrieve virtual card metadata by token."""
        return self._cards.get(card_token)

    def process_payment(
        self,
        request: VirtualCardPaymentRequest,
        confirmed_by_user: bool = False,
        current_time: float | None = None,
    ) -> VirtualCardPaymentReceipt:
        """Execute settlement using a single-use virtual card token."""
        now = time.time() if current_time is None else current_time
        receipt_id = f"rcpt-{uuid.uuid4().hex[:12]}"
        card = self._cards.get(request.card_token)

        if not card:
            return VirtualCardPaymentReceipt(
                receipt_id=receipt_id,
                card_token=request.card_token,
                charged_amount=0.0,
                currency=request.currency,
                is_success=False,
                status="failed_card_not_found",
                merchant_name=request.merchant_name,
                requires_hitl_escalation=False,
                message="Virtual card token does not exist",
            )

        if card.status != VirtualCardStatus.ACTIVE:
            return VirtualCardPaymentReceipt(
                receipt_id=receipt_id,
                card_token=request.card_token,
                charged_amount=0.0,
                currency=request.currency,
                is_success=False,
                status=f"failed_card_{card.status.value}",
                merchant_name=request.merchant_name,
                requires_hitl_escalation=False,
                message=f"Virtual card is not active (current status: {card.status.value})",
            )

        if now > card.expires_at:
            # Mark expired
            self._update_card_status(card, VirtualCardStatus.EXPIRED)
            return VirtualCardPaymentReceipt(
                receipt_id=receipt_id,
                card_token=request.card_token,
                charged_amount=0.0,
                currency=request.currency,
                is_success=False,
                status="failed_card_expired",
                merchant_name=request.merchant_name,
                requires_hitl_escalation=False,
                message="Virtual card has expired",
            )

        if request.amount > card.spending_limit:
            return VirtualCardPaymentReceipt(
                receipt_id=receipt_id,
                card_token=request.card_token,
                charged_amount=0.0,
                currency=request.currency,
                is_success=False,
                status="failed_limit_exceeded",
                merchant_name=request.merchant_name,
                requires_hitl_escalation=False,
                message=(
                    f"Requested amount ({request.amount:.2f} {request.currency}) "
                    f"exceeds spending limit ({card.spending_limit:.2f} {card.currency})"
                ),
            )

        if card.requires_hitl and not confirmed_by_user:
            return VirtualCardPaymentReceipt(
                receipt_id=receipt_id,
                card_token=request.card_token,
                charged_amount=0.0,
                currency=request.currency,
                is_success=False,
                status="pending_hitl_confirmation",
                merchant_name=request.merchant_name,
                requires_hitl_escalation=True,
                message="Transaction amount mandates explicit Human-in-the-Loop user approval",
            )

        # Successful payment -> mark REDEEMED
        updated_card = SingleUseVirtualCard(
            card_token=card.card_token,
            masked_card_number=card.masked_card_number,
            currency=card.currency,
            spending_limit=card.spending_limit,
            amount_spent=request.amount,
            status=VirtualCardStatus.REDEEMED,
            created_at=card.created_at,
            expires_at=card.expires_at,
            requires_hitl=card.requires_hitl,
        )
        self._cards[card.card_token] = updated_card
        logger.info(
            "Settled payment %s for %s %s at merchant '%s'",
            receipt_id,
            request.amount,
            request.currency,
            request.merchant_name,
        )

        return VirtualCardPaymentReceipt(
            receipt_id=receipt_id,
            card_token=request.card_token,
            charged_amount=request.amount,
            currency=request.currency,
            is_success=True,
            status="settled",
            merchant_name=request.merchant_name,
            requires_hitl_escalation=False,
            message=f"Successfully charged {request.amount:.2f} {request.currency} via blind virtual card",
        )

    def cancel_card(self, card_token: str) -> bool:
        """Cancel an active virtual card."""
        card = self._cards.get(card_token)
        if not card or card.status != VirtualCardStatus.ACTIVE:
            return False
        self._update_card_status(card, VirtualCardStatus.CANCELLED)
        return True

    def _update_card_status(
        self, card: SingleUseVirtualCard, new_status: VirtualCardStatus
    ) -> None:
        self._cards[card.card_token] = SingleUseVirtualCard(
            card_token=card.card_token,
            masked_card_number=card.masked_card_number,
            currency=card.currency,
            spending_limit=card.spending_limit,
            amount_spent=card.amount_spent,
            status=new_status,
            created_at=card.created_at,
            expires_at=card.expires_at,
            requires_hitl=card.requires_hitl,
        )
