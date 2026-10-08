"""Financial Action Boundary Guard and Wallet Credential Air-Gap Controller.

[INPUT]
- FinancialTransactionIntent, SpendingCeilingPolicy, confirmation card IDs, raw text payloads.

[OUTPUT]
- TransactionEvaluationResult detailing whether an asset action may execute autonomously,
  triggers a daily ceiling circuit breaker, or requires human-in-the-loop multi-sig card approval.
- AirGappedCredentialViolationError raised if private keys enter agent scope.

[POS]
- Harness core security module inspired by Hermes/Telegram crypto bot risk management.
- Guarantees strict air-gapping of asset credentials and hard daily spending circuit breakers.
"""

from __future__ import annotations

import re
import threading
import time
import uuid
from datetime import UTC, datetime

from myrm_agent_harness.core.security.financial_boundary.types import (
    AirGappedCredentialViolationError,
    FinancialConfirmationCard,
    FinancialTransactionIntent,
    SpendingCeilingPolicy,
    TransactionEvaluationResult,
)

# Regex matching raw EVM 64-hex private keys (with or without 0x prefix)
_HEX_KEY_REGEX = re.compile(r"\b(0x)?[a-fA-F0-9]{64}\b")
# Keywords indicative of mnemonic seed phrases
_SEED_PHRASE_REGEX = re.compile(
    r"\b(mnemonic|seed phrase|private key|secret key)\s*[:=]\s*['\"]?[a-zA-Z\s]{24,}['\"]?",
    re.IGNORECASE,
)


class FinancialActionBoundaryGuard:
    """Controller enforcing asset boundary rules, air-gapped credentials, and daily spending ceilings."""

    def __init__(self, policy: SpendingCeilingPolicy | None = None) -> None:
        self._policy = policy or SpendingCeilingPolicy()
        # date_key (YYYY-MM-DD) -> cumulative USD spend
        self._daily_spend: dict[str, float] = {}
        self._cards: dict[str, FinancialConfirmationCard] = {}
        self._lock = threading.Lock()

    @property
    def policy(self) -> SpendingCeilingPolicy:
        """Access active spending policy."""
        return self._policy

    @staticmethod
    def _get_today_key() -> str:
        """Deterministic UTC date key."""
        return datetime.now(UTC).strftime("%Y-%m-%d")

    @classmethod
    def assert_no_private_keys(cls, text: str) -> None:
        """Verify that text does not contain raw private keys or seed phrases.

        Raises:
            AirGappedCredentialViolationError: If sensitive signing credentials are found.
        """
        if not text:
            return

        if _HEX_KEY_REGEX.search(text):
            raise AirGappedCredentialViolationError(
                "Physical air-gap violation: Raw 64-hexadecimal private key detected in payload! "
                "Private keys must NEVER enter agent prompt or context."
            )

        if _SEED_PHRASE_REGEX.search(text):
            raise AirGappedCredentialViolationError(
                "Physical air-gap violation: Mnemonic recovery phrase detected in payload! "
                "Signing seed material must remain physically air-gapped from agent execution."
            )

    def get_current_daily_spend(self, date_key: str | None = None) -> float:
        """Get total USD amount executed today."""
        key = date_key or self._get_today_key()
        with self._lock:
            return self._daily_spend.get(key, 0.0)

    def get_remaining_daily_limit(self, date_key: str | None = None) -> float:
        """Get remaining allowable USD spend for today before hard circuit breaker."""
        spent = self.get_current_daily_spend(date_key)
        return max(0.0, self._policy.daily_ceiling_usd - spent)

    def evaluate_intent(self, intent: FinancialTransactionIntent) -> TransactionEvaluationResult:
        """Evaluate a proposed financial transaction against air-gapping and spending rules."""
        # 1. Assert air-gapped credential safety in justification and recipient
        self.assert_no_private_keys(intent.justification)
        self.assert_no_private_keys(intent.recipient_address)

        today = self._get_today_key()
        usd_val = intent.estimated_usd_value

        with self._lock:
            current_spend = self._daily_spend.get(today, 0.0)
            remaining = max(0.0, self._policy.daily_ceiling_usd - current_spend)

        # 2. Check asset symbol whitelist
        if intent.asset_symbol.upper() not in self._policy.allowed_asset_symbols:
            return TransactionEvaluationResult(
                intent_id=intent.intent_id,
                permitted_autonomous_execution=False,
                requires_human_confirmation=False,
                circuit_breaker_triggered=False,
                current_daily_spend_usd=current_spend,
                remaining_daily_limit_usd=remaining,
                reason=f"Asset symbol '{intent.asset_symbol}' is not whitelisted by policy.",
            )

        # 3. Check daily ceiling circuit breaker
        if current_spend + usd_val > self._policy.daily_ceiling_usd:
            return TransactionEvaluationResult(
                intent_id=intent.intent_id,
                permitted_autonomous_execution=False,
                requires_human_confirmation=False,
                circuit_breaker_triggered=True,
                current_daily_spend_usd=current_spend,
                remaining_daily_limit_usd=remaining,
                reason=(
                    f"Daily ceiling circuit breaker triggered! Attempted ${usd_val:.2f} + current ${current_spend:.2f} "
                    f"exceeds daily ceiling of ${self._policy.daily_ceiling_usd:.2f}."
                ),
            )

        # 4. Check single transaction threshold
        if usd_val > self._policy.single_transaction_ceiling_usd:
            # Escalates to human confirmation card
            card_id = f"card_fin_{uuid.uuid4().hex[:10]}"
            card = FinancialConfirmationCard(
                card_id=card_id,
                intent=intent,
                status="pending",
            )
            with self._lock:
                self._cards[card_id] = card

            return TransactionEvaluationResult(
                intent_id=intent.intent_id,
                permitted_autonomous_execution=False,
                requires_human_confirmation=True,
                circuit_breaker_triggered=False,
                current_daily_spend_usd=current_spend,
                remaining_daily_limit_usd=remaining,
                reason=(
                    f"Transaction value ${usd_val:.2f} exceeds single autonomous ceiling "
                    f"(${self._policy.single_transaction_ceiling_usd:.2f}). "
                    "Confirmation card generated for human two-person sign-off."
                ),
                confirmation_card_id=card_id,
            )

        # 5. Micro-transaction within autonomous bounds -> record spend
        with self._lock:
            self._daily_spend[today] = current_spend + usd_val
            new_current = self._daily_spend[today]
            new_remaining = max(0.0, self._policy.daily_ceiling_usd - new_current)

        return TransactionEvaluationResult(
            intent_id=intent.intent_id,
            permitted_autonomous_execution=True,
            requires_human_confirmation=False,
            circuit_breaker_triggered=False,
            current_daily_spend_usd=new_current,
            remaining_daily_limit_usd=new_remaining,
            reason="Micro-transaction within approved autonomous spending ceiling.",
        )

    def approve_card(self, card_id: str) -> FinancialConfirmationCard:
        """Approve an asset confirmation card and deduct from daily allowance."""
        today = self._get_today_key()
        with self._lock:
            card = self._cards.get(card_id)
            if not card:
                raise KeyError(f"Confirmation card '{card_id}' not found")
            if time.time() > card.expires_at:
                expired = FinancialConfirmationCard(
                    card_id=card.card_id,
                    intent=card.intent,
                    status="expired",
                    created_at=card.created_at,
                    expires_at=card.expires_at,
                )
                self._cards[card_id] = expired
                raise ValueError("Confirmation card has expired")

            # Deduct approved amount from daily limit
            current_spend = self._daily_spend.get(today, 0.0)
            self._daily_spend[today] = current_spend + card.intent.estimated_usd_value

            approved = FinancialConfirmationCard(
                card_id=card.card_id,
                intent=card.intent,
                status="approved",
                created_at=card.created_at,
                expires_at=card.expires_at,
            )
            self._cards[card_id] = approved
            return approved

    def reject_card(self, card_id: str) -> FinancialConfirmationCard:
        """Reject an asset confirmation card."""
        with self._lock:
            card = self._cards.get(card_id)
            if not card:
                raise KeyError(f"Confirmation card '{card_id}' not found")

            rejected = FinancialConfirmationCard(
                card_id=card.card_id,
                intent=card.intent,
                status="rejected",
                created_at=card.created_at,
                expires_at=card.expires_at,
            )
            self._cards[card_id] = rejected
            return rejected

    def get_card(self, card_id: str) -> FinancialConfirmationCard | None:
        """Get confirmation card by ID."""
        with self._lock:
            return self._cards.get(card_id)

    def list_cards(self, status: str | None = None) -> list[FinancialConfirmationCard]:
        """List all financial confirmation cards."""
        with self._lock:
            cards = list(self._cards.values())
        if status:
            return [c for c in cards if c.status == status]
        return cards
