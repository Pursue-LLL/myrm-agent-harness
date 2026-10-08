"""Single-Use Ephemeral Credential and Payment Proxy.

Generates one-time virtual tokens and cards so real credentials and payment accounts
never reside in agent memory or get exposed to untrusted external APIs.
"""

from __future__ import annotations

import secrets
import threading
import uuid
from datetime import UTC, datetime, timedelta

from .types import (
    SingleUseToken,
    TokenRedemptionResult,
    TokenType,
)


class SingleUseCredentialProxy:
    """Thread-safe broker managing short-lived, single-use credentials and payment cards."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tokens: dict[str, SingleUseToken] = {}
        # Mapping from virtual_token string to token_id
        self._lookup: dict[str, str] = {}

    def issue_token(
        self,
        token_type: TokenType = TokenType.VIRTUAL_PAYMENT_CARD,
        max_amount: float = 100.0,
        currency: str = "USD",
        bound_recipient: str = "*",
        ttl_seconds: int = 300,
    ) -> SingleUseToken:
        """Issue an isolated single-use virtual token with budget and recipient bounds."""
        token_id = f"tok_id_{uuid.uuid4().hex[:12]}"
        prefix = token_type.value[:4]
        virtual_token = f"link_vtok_{prefix}_{secrets.token_hex(16)}"
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=ttl_seconds)

        token = SingleUseToken(
            token_id=token_id,
            virtual_token=virtual_token,
            token_type=token_type,
            max_amount=max_amount,
            currency=currency.upper(),
            bound_recipient=bound_recipient.lower(),
            is_consumed=False,
            expires_at=expires_at,
            created_at=now,
        )

        with self._lock:
            self._tokens[token_id] = token
            self._lookup[virtual_token] = token_id

        return token

    def redeem_token(
        self,
        virtual_token: str,
        amount: float,
        currency: str,
        recipient: str,
    ) -> TokenRedemptionResult:
        """Attempt to consume a single-use token, enforcing one-time use, budget, and recipient."""
        with self._lock:
            token_id = self._lookup.get(virtual_token)
            if token_id is None or token_id not in self._tokens:
                return TokenRedemptionResult(
                    token_id="unknown",
                    success=False,
                    reason="Invalid or non-existent virtual token",
                )

            token = self._tokens[token_id]

            # 1. Check if already consumed (prevent replay / double-spending)
            if token.is_consumed:
                return TokenRedemptionResult(
                    token_id=token_id,
                    success=False,
                    reason="Single-use token has already been consumed (replay attempt blocked)",
                )

            # 2. Check expiration
            now = datetime.now(UTC)
            if token.expires_at < now:
                return TokenRedemptionResult(
                    token_id=token_id,
                    success=False,
                    reason=f"Single-use token expired at {token.expires_at.isoformat()}",
                )

            # 3. Check currency match
            if token.currency != currency.upper():
                return TokenRedemptionResult(
                    token_id=token_id,
                    success=False,
                    reason=f"Currency mismatch: expected {token.currency}, got {currency.upper()}",
                )

            # 4. Check budget limit
            if amount > token.max_amount:
                return TokenRedemptionResult(
                    token_id=token_id,
                    success=False,
                    reason=(
                        f"Amount {amount:.2f} {token.currency} exceeds token authorization "
                        f"ceiling {token.max_amount:.2f} {token.currency}"
                    ),
                )

            # 5. Check bound recipient
            normalized_recipient = recipient.lower().strip()
            if (
                token.bound_recipient != "*"
                and token.bound_recipient not in normalized_recipient
                and normalized_recipient not in token.bound_recipient
            ):
                return TokenRedemptionResult(
                    token_id=token_id,
                    success=False,
                    reason=(
                        f"Recipient mismatch: token is strictly bound to '{token.bound_recipient}', "
                        f"attempted redemption by '{recipient}'"
                    ),
                )

            # 6. Consume token atomically
            consumed_token = SingleUseToken(
                token_id=token.token_id,
                virtual_token=token.virtual_token,
                token_type=token.token_type,
                max_amount=token.max_amount,
                currency=token.currency,
                bound_recipient=token.bound_recipient,
                is_consumed=True,
                expires_at=token.expires_at,
                created_at=token.created_at,
            )
            self._tokens[token_id] = consumed_token

            return TokenRedemptionResult(
                token_id=token_id,
                success=True,
                reason="Single-use credential successfully authorized and redeemed",
            )

    def get_token(self, token_id: str) -> SingleUseToken | None:
        """Retrieve token record by token_id."""
        with self._lock:
            return self._tokens.get(token_id)

    def revoke_token(self, token_id: str) -> bool:
        """Immediately invalidate and revoke an active token."""
        with self._lock:
            token = self._tokens.get(token_id)
            if token is None:
                return False

            self._tokens[token_id] = SingleUseToken(
                token_id=token.token_id,
                virtual_token=token.virtual_token,
                token_type=token.token_type,
                max_amount=token.max_amount,
                currency=token.currency,
                bound_recipient=token.bound_recipient,
                is_consumed=True,
                expires_at=token.expires_at,
                created_at=token.created_at,
            )
            return True

    def list_tokens(self, active_only: bool = False) -> list[SingleUseToken]:
        """List token records, optionally filtering for unconsumed, unexpired tokens."""
        now = datetime.now(UTC)
        with self._lock:
            tokens = list(self._tokens.values())
            if not active_only:
                return tokens
            return [t for t in tokens if not t.is_consumed and t.expires_at >= now]
