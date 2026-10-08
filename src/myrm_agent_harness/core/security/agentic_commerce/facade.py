"""
[POS] src/myrm_agent_harness/core/security/agentic_commerce/facade.py
[INPUT] time, uuid, typing
[OUTPUT] AgenticCommerceSuite

Unified facade for Autonomous Agent Commerce Protocol & Zero-Knowledge Financial Vault Suite.
Coordinates structured intent generation, spend guardrail arbitration, zero-knowledge
ephemeral token minting, and final ledger settlement.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import logging
import time
import uuid

from .financial_spend_guardrail import FinancialSpendGuardrail
from .types import (
    AgenticCommerceMetrics,
    CommerceTransactionStatus,
    EphemeralPaymentToken,
    FinancialBudgetPolicy,
    MerchantSpec,
    PaymentIntent,
    PaymentRailEnum,
    SettlementReceipt,
)
from .zero_knowledge_vault import ZeroKnowledgeFinancialVault

logger = logging.getLogger(__name__)


class AgenticCommerceSuite:
    """Unified security facade governing agentic commerce protocol and zero-knowledge financial vault."""

    def __init__(
        self,
        budget_policy: FinancialBudgetPolicy | None = None,
        masked_card_last4: str = "4242",
    ) -> None:
        self._vault = ZeroKnowledgeFinancialVault(masked_card_last4=masked_card_last4)
        self._guardrail = FinancialSpendGuardrail(policy=budget_policy)
        self._metrics = AgenticCommerceMetrics()

    @property
    def metrics(self) -> AgenticCommerceMetrics:
        """Operational metrics tracking."""
        return self._metrics

    @property
    def budget_policy(self) -> FinancialBudgetPolicy:
        """Active financial budget policy."""
        return self._guardrail.policy

    def create_payment_intent(
        self,
        merchant: MerchantSpec,
        amount_cents: int,
        currency: str = "USD",
        line_items: tuple[str, ...] = (),
        payment_rail: PaymentRailEnum = PaymentRailEnum.STRIPE_AGENT_VIRTUAL_CARD,
    ) -> tuple[PaymentIntent, CommerceTransactionStatus, str, EphemeralPaymentToken | None]:
        """Create structured payment intent, evaluate against budget guardrail, and conditionally mint token."""
        intent_id = f"pi-{uuid.uuid4().hex[:12]}"
        intent = PaymentIntent(
            intent_id=intent_id,
            merchant=merchant,
            amount_cents=amount_cents,
            currency=currency,
            line_items=line_items,
            payment_rail=payment_rail,
            created_at=time.time(),
        )

        self._metrics.intents_created_total += 1
        status, explanation = self._guardrail.evaluate_intent(intent)

        if status == CommerceTransactionStatus.AUTO_APPROVED:
            self._metrics.auto_approved_total += 1
            token = self._vault.mint_ephemeral_token(
                intent_id=intent_id,
                max_amount_cents=amount_cents,
            )
            self._metrics.tokens_minted_total += 1
            return intent, status, explanation, token

        if status == CommerceTransactionStatus.PENDING_HITL_CONFIRMATION:
            self._metrics.hitl_approvals_requested_total += 1
            return intent, status, explanation, None

        # REJECTED_BUDGET_EXCEEDED
        self._metrics.budget_rejections_total += 1
        return intent, status, explanation, None

    def confirm_hitl_and_mint(self, intent_id: str) -> tuple[PaymentIntent, EphemeralPaymentToken]:
        """User confirms pending HITL payment intent, authorizing zero-knowledge token minting."""
        intent = self._guardrail.approve_hitl(intent_id)
        token = self._vault.mint_ephemeral_token(
            intent_id=intent.intent_id,
            max_amount_cents=intent.amount_cents,
        )
        self._metrics.hitl_approved_total += 1
        self._metrics.tokens_minted_total += 1
        return intent, token

    def deny_hitl(self, intent_id: str) -> PaymentIntent:
        """User explicitly rejects pending HITL transaction ticket."""
        intent = self._guardrail.reject_hitl(intent_id)
        self._metrics.hitl_denied_total += 1
        return intent

    def settle_transaction(
        self,
        token_string: str,
        intent: PaymentIntent,
    ) -> SettlementReceipt:
        """Execute settlement against ephemeral token and update cumulative daily ledger."""
        self._vault.validate_and_consume_token(
            token_string=token_string,
            charge_amount_cents=intent.amount_cents,
        )

        self._guardrail.record_settlement(intent.amount_cents)
        self._metrics.settlements_completed_total += 1
        self._metrics.total_spent_cents += intent.amount_cents

        receipt_id = f"rcpt-{uuid.uuid4().hex[:12]}"
        confirmation_code = f"AUTH_{uuid.uuid4().hex[:8].upper()}"

        receipt = SettlementReceipt(
            receipt_id=receipt_id,
            intent_id=intent.intent_id,
            status=CommerceTransactionStatus.SETTLED,
            amount_cents=intent.amount_cents,
            currency=intent.currency,
            merchant_name=intent.merchant.merchant_name,
            payment_rail=intent.payment_rail,
            confirmation_code=confirmation_code,
            settled_at=time.time(),
        )
        logger.info("Settled agentic commerce transaction receipt %s", receipt_id)
        return receipt

    def get_budget_status(self) -> dict[str, int]:
        """Query current daily spend and remaining allowance in cents."""
        return {
            "daily_hard_cap_cents": self._guardrail.policy.daily_hard_cap_cents,
            "daily_spent_cents": self._guardrail.daily_spent_cents,
            "remaining_budget_cents": self._guardrail.get_remaining_daily_budget_cents(),
            "single_transaction_max_cents": self._guardrail.policy.single_transaction_max_cents,
            "auto_approval_threshold_cents": self._guardrail.policy.auto_approval_threshold_cents,
        }

    def update_budget_policy(self, new_policy: FinancialBudgetPolicy) -> None:
        """Update active financial budget policy."""
        self._guardrail.update_policy(new_policy)

    def list_pending_hitl_intents(self) -> list[PaymentIntent]:
        """List all intents awaiting human approval."""
        return self._guardrail.list_pending_hitl_intents()
