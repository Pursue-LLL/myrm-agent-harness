"""
[POS] src/myrm_agent_harness/core/security/agentic_commerce/financial_spend_guardrail.py
[INPUT] logging, threading, time, typing
[OUTPUT] FinancialSpendGuardrail

Multi-tier spend watchdog enforcing daily hard budget caps, single-transaction limits,
merchant category allowlists, and human-in-the-loop (HITL) approval gates.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import logging
import threading
import time

from .types import (
    CommerceTransactionStatus,
    FinancialBudgetPolicy,
    PaymentIntent,
)

logger = logging.getLogger(__name__)


class FinancialSpendGuardrail:
    """Enforces multi-tier spending budgets and determines auto-approval vs HITL requirements."""

    def __init__(self, policy: FinancialBudgetPolicy | None = None) -> None:
        self._lock = threading.RLock()
        self._policy: FinancialBudgetPolicy = policy or FinancialBudgetPolicy()
        self._daily_spent_cents: int = 0
        self._last_reset_epoch: float = time.time()
        self._pending_hitl_intents: dict[str, PaymentIntent] = {}

    @property
    def policy(self) -> FinancialBudgetPolicy:
        """Active financial spend budget policy."""
        with self._lock:
            return self._policy

    @property
    def daily_spent_cents(self) -> int:
        """Current amount spent today in cents."""
        with self._lock:
            self._check_and_reset_daily_window()
            return self._daily_spent_cents

    def update_policy(self, new_policy: FinancialBudgetPolicy) -> None:
        """Update active financial budget policy."""
        with self._lock:
            self._policy = new_policy

    def get_remaining_daily_budget_cents(self) -> int:
        """Remaining daily allowance in cents before hard ceiling is breached."""
        with self._lock:
            self._check_and_reset_daily_window()
            return max(0, self._policy.daily_hard_cap_cents - self._daily_spent_cents)

    def evaluate_intent(self, intent: PaymentIntent) -> tuple[CommerceTransactionStatus, str]:
        """Evaluate payment intent against budget policy and determine authorization tier."""
        with self._lock:
            self._check_and_reset_daily_window()

            # 1. Category check
            if intent.merchant.category not in self._policy.allowed_categories:
                explanation = (
                    f"Merchant category '{intent.merchant.category}' is not in allowed list "
                    f"{self._policy.allowed_categories}"
                )
                logger.warning("Agentic commerce rejected: %s", explanation)
                return CommerceTransactionStatus.REJECTED_BUDGET_EXCEEDED, explanation

            # 2. Single transaction cap check
            if intent.amount_cents > self._policy.single_transaction_max_cents:
                explanation = (
                    f"Transaction amount ({intent.amount_cents} cents) exceeds single-purchase "
                    f"hard ceiling ({self._policy.single_transaction_max_cents} cents)"
                )
                logger.warning("Agentic commerce rejected: %s", explanation)
                return CommerceTransactionStatus.REJECTED_BUDGET_EXCEEDED, explanation

            # 3. Daily hard cap check
            projected_spend = self._daily_spent_cents + intent.amount_cents
            if projected_spend > self._policy.daily_hard_cap_cents:
                explanation = (
                    f"Projected daily spend ({projected_spend} cents) would breach daily hard cap "
                    f"({self._policy.daily_hard_cap_cents} cents). Current spent: {self._daily_spent_cents} cents"
                )
                logger.warning("Agentic commerce rejected: %s", explanation)
                return CommerceTransactionStatus.REJECTED_BUDGET_EXCEEDED, explanation

            # 4. Auto-approval vs HITL gate
            if (
                intent.amount_cents <= self._policy.auto_approval_threshold_cents
                and intent.merchant.is_whitelisted
            ):
                return (
                    CommerceTransactionStatus.AUTO_APPROVED,
                    f"Auto-approved: under auto-threshold ({self._policy.auto_approval_threshold_cents} cents).",
                )

            # Requires human-in-the-loop secondary approval
            self._pending_hitl_intents[intent.intent_id] = intent
            return (
                CommerceTransactionStatus.PENDING_HITL_CONFIRMATION,
                "Requires user confirmation: amount exceeds auto-approval threshold or merchant unverified.",
            )

    def approve_hitl(self, intent_id: str) -> PaymentIntent:
        """Confirm and clear HITL ticket for execution."""
        with self._lock:
            intent = self._pending_hitl_intents.pop(intent_id, None)
            if intent is None:
                raise ValueError(f"No pending HITL authorization ticket found for intent '{intent_id}'")
            return intent

    def reject_hitl(self, intent_id: str) -> PaymentIntent:
        """Deny and discard pending HITL ticket."""
        with self._lock:
            intent = self._pending_hitl_intents.pop(intent_id, None)
            if intent is None:
                raise ValueError(f"No pending HITL authorization ticket found for intent '{intent_id}'")
            return intent

    def list_pending_hitl_intents(self) -> list[PaymentIntent]:
        """List all intents currently awaiting human approval."""
        with self._lock:
            return list(self._pending_hitl_intents.values())

    def record_settlement(self, amount_cents: int) -> None:
        """Increment cumulative daily spend following confirmed transaction settlement."""
        with self._lock:
            self._check_and_reset_daily_window()
            self._daily_spent_cents += amount_cents

    def _check_and_reset_daily_window(self) -> None:
        """Reset daily cumulative counter if 24 hours have elapsed."""
        now = time.time()
        if now - self._last_reset_epoch >= 86400.0:
            self._daily_spent_cents = 0
            self._last_reset_epoch = now
            logger.info("Daily financial spend guardrail window reset.")
