"""
[POS] src/myrm_agent_harness/core/security/autonomous_signing_airgap/quota_guard.py
[INPUT] types
[OUTPUT] PayloadAstInspectorAndQuotaGuard
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import logging

from .types import (
    SigningDecisionStatus,
    SigningQuotaConfig,
    TransactionPayload,
)

logger = logging.getLogger(__name__)


class PayloadAstInspectorAndQuotaGuard:
    """Inspects transaction recipients and asserts against financial quota thresholds."""

    def __init__(self, config: SigningQuotaConfig | None = None) -> None:
        self._config = config or SigningQuotaConfig()

    @property
    def config(self) -> SigningQuotaConfig:
        return self._config

    def update_config(self, new_config: SigningQuotaConfig) -> None:
        """Update quota rules dynamically."""
        self._config = new_config

    def inspect_and_evaluate(
        self, payload: TransactionPayload, current_daily_spent: float
    ) -> tuple[SigningDecisionStatus, str]:
        """Perform semantic whitelist and quota assertion for proposed transaction.

        Returns tuple of (SigningDecisionStatus, diagnostic_reason).
        """
        if payload.amount <= 0.0:
            return (
                SigningDecisionStatus.REJECTED_QUOTA_EXCEEDED,
                f"Transaction amount must be strictly positive, got {payload.amount}",
            )

        # 1. Recipient whitelist enforcement
        if self._config.trusted_recipients:
            recipient_lower = payload.recipient.strip().lower()
            whitelist_lower = {r.strip().lower() for r in self._config.trusted_recipients}
            if recipient_lower not in whitelist_lower:
                return (
                    SigningDecisionStatus.REJECTED_UNTRUSTED_RECIPIENT,
                    f"Recipient '{payload.recipient}' is not in trusted recipient whitelist",
                )

        # 2. Cumulative daily quota enforcement
        projected_daily = current_daily_spent + payload.amount
        if projected_daily > self._config.daily_cumulative_limit:
            return (
                SigningDecisionStatus.REJECTED_QUOTA_EXCEEDED,
                (
                    f"Transaction amount {payload.amount} exceeds remaining daily quota. "
                    f"Current spent: {current_daily_spent:.2f}, limit: {self._config.daily_cumulative_limit:.2f}"
                ),
            )

        # 3. Single transaction threshold & Step-Up HITL trigger
        if payload.amount > self._config.single_tx_limit:
            # If transaction is more than 3x single limit, reject immediately
            if payload.amount > self._config.single_tx_limit * 3.0:
                return (
                    SigningDecisionStatus.REJECTED_QUOTA_EXCEEDED,
                    (
                        f"Transaction amount {payload.amount} severely exceeds single transaction ceiling "
                        f"({self._config.single_tx_limit * 3.0:.2f})"
                    ),
                )
            # Otherwise step-up to Human-in-the-Loop for one-time confirmation
            return (
                SigningDecisionStatus.REQUIRE_HITL_STEP_UP,
                (
                    f"Transaction amount {payload.amount} exceeds silent single limit "
                    f"({self._config.single_tx_limit:.2f}); requires human step-up approval"
                ),
            )

        # 4. Safe for silent headless signing
        return (
            SigningDecisionStatus.SILENT_AUTHORIZED,
            "Transaction passed all recipient whitelist and quota checks",
        )
