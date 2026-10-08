"""
[POS] src/myrm_agent_harness/core/security/agentic_commerce/zero_knowledge_vault.py
[INPUT] secrets, threading, time, uuid, typing
[OUTPUT] ZeroKnowledgeFinancialVault

Implements Zero-Knowledge Financial Vault where sensitive primary account numbers (PAN)
and CVVs are held isolated in secure enclave. Issues single-use ephemeral tokens to sandbox.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import logging
import secrets
import threading
import time
import uuid

from .types import EphemeralPaymentToken

logger = logging.getLogger(__name__)


class ZeroKnowledgeFinancialVault:
    """Isolates real financial instruments and issues tightly scoped, single-use payment tokens."""

    def __init__(self, masked_card_last4: str = "4242") -> None:
        self._lock = threading.RLock()
        self._masked_card_last4 = masked_card_last4
        self._tokens: dict[str, EphemeralPaymentToken] = {}

    @property
    def masked_card_last4(self) -> str:
        """Masked last 4 digits of vault-managed card."""
        return self._masked_card_last4

    def mint_ephemeral_token(
        self,
        intent_id: str,
        max_amount_cents: int,
        ttl_seconds: float = 300.0,
    ) -> EphemeralPaymentToken:
        """Mint a single-use ephemeral virtual payment token bound to a specific intent and cap."""
        with self._lock:
            token_id = f"tok-{uuid.uuid4().hex[:12]}"
            token_string = f"ephem_sec_{secrets.token_urlsafe(24)}"
            now = time.time()

            token = EphemeralPaymentToken(
                token_id=token_id,
                intent_id=intent_id,
                masked_card_last4=self._masked_card_last4,
                token_string=token_string,
                max_amount_cents=max_amount_cents,
                expires_at=now + ttl_seconds,
                is_consumed=False,
            )
            self._tokens[token_string] = token
            logger.info("Minted ephemeral payment token %s for intent %s", token_id, intent_id)
            return token

    def validate_and_consume_token(
        self,
        token_string: str,
        charge_amount_cents: int,
    ) -> EphemeralPaymentToken:
        """Validate token invariants and mark consumed (single-use semantics)."""
        with self._lock:
            token = self._tokens.get(token_string)
            if token is None:
                raise ValueError("Invalid or unknown ephemeral payment token")

            if token.is_consumed:
                raise ValueError("Ephemeral token has already been consumed (replay blocked)")

            if time.time() > token.expires_at:
                raise ValueError("Ephemeral payment token has expired")

            if charge_amount_cents > token.max_amount_cents:
                raise ValueError(
                    f"Charge amount ({charge_amount_cents} cents) exceeds token authorized cap "
                    f"({token.max_amount_cents} cents)"
                )

            consumed_token = EphemeralPaymentToken(
                token_id=token.token_id,
                intent_id=token.intent_id,
                masked_card_last4=token.masked_card_last4,
                token_string=token.token_string,
                max_amount_cents=token.max_amount_cents,
                expires_at=token.expires_at,
                is_consumed=True,
            )
            self._tokens[token_string] = consumed_token
            logger.info("Consumed ephemeral payment token %s successfully", token.token_id)
            return consumed_token

    def revoke_token(self, token_string: str) -> bool:
        """Explicitly cancel and revoke an unconsumed token."""
        with self._lock:
            return self._tokens.pop(token_string, None) is not None
