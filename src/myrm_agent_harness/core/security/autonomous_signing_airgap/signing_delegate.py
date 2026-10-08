"""
[POS] src/myrm_agent_harness/core/security/autonomous_signing_airgap/signing_delegate.py
[INPUT] hashlib, hmac, time, types, quota_guard
[OUTPUT] KeyringAirgapSigningDelegate
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time

from .quota_guard import PayloadAstInspectorAndQuotaGuard
from .types import (
    SigningDecisionStatus,
    SigningEvaluationVerdict,
    TransactionPayload,
    WalletAirgapMetrics,
)

logger = logging.getLogger(__name__)


class KeyringAirgapSigningDelegate:
    """Airgapped signing delegate isolating secrets in native OS keyring mock/sandbox."""

    def __init__(
        self,
        quota_guard: PayloadAstInspectorAndQuotaGuard | None = None,
        metrics: WalletAirgapMetrics | None = None,
        mock_keyring_seed: str = "myrm-local-keyring-airgap-seed-2026",
    ) -> None:
        self._quota_guard = quota_guard or PayloadAstInspectorAndQuotaGuard()
        self._metrics = metrics or WalletAirgapMetrics()
        self._mock_seed = mock_keyring_seed.encode()
        self._is_kill_switch_active: bool = False
        self._kill_switch_reason: str = ""
        self._current_daily_spent: float = 0.0
        self._pending_hitl_txs: dict[str, TransactionPayload] = {}

    @property
    def quota_guard(self) -> PayloadAstInspectorAndQuotaGuard:
        return self._quota_guard

    @property
    def metrics(self) -> WalletAirgapMetrics:
        return self._metrics

    @property
    def is_kill_switch_active(self) -> bool:
        return self._is_kill_switch_active

    @property
    def kill_switch_reason(self) -> str:
        return self._kill_switch_reason

    @property
    def current_daily_spent(self) -> float:
        return self._current_daily_spent

    def trigger_kill_switch(self, reason: str = "Emergency Freeze Triggered") -> None:
        """Immediately freeze all signing capabilities via physical airgap kill-switch."""
        self._is_kill_switch_active = True
        self._kill_switch_reason = reason
        # Drop all pending unconfirmed requests immediately to prevent race conditions
        self._pending_hitl_txs.clear()
        logger.critical("EMERGENCY KILL-SWITCH ACTIVATED: %s", reason)

    def release_kill_switch(self) -> None:
        """Disengage kill-switch and restore signing operations."""
        self._is_kill_switch_active = False
        self._kill_switch_reason = ""
        logger.info("Emergency kill-switch released. Normal signing restored.")

    def reset_daily_quota(self, starting_amount: float = 0.0) -> None:
        """Reset accumulated daily expenditure tracker."""
        self._current_daily_spent = max(0.0, starting_amount)

    def evaluate_and_sign(
        self, payload: TransactionPayload
    ) -> SigningEvaluationVerdict:
        """Evaluate incoming transaction payload against airgap kill-switch and quota guard."""
        self._metrics.evaluations_total += 1

        # 1. Kill-switch check
        if self._is_kill_switch_active:
            self._metrics.kill_switch_blocked_total += 1
            return SigningEvaluationVerdict(
                decision=SigningDecisionStatus.FROZEN_BY_KILL_SWITCH,
                is_approved_to_sign=False,
                signature_token=None,
                diagnostic_reason=f"Emergency kill-switch active: {self._kill_switch_reason}",
                tx_id=payload.tx_id,
                remaining_daily_allowance=self._calc_remaining_allowance(),
            )

        # 2. Quota & Recipient Inspection
        decision, reason = self._quota_guard.inspect_and_evaluate(
            payload, self._current_daily_spent
        )

        if decision == SigningDecisionStatus.SILENT_AUTHORIZED:
            self._metrics.silent_signed_total += 1
            self._current_daily_spent += payload.amount
            sig = self._generate_signature(payload)
            return SigningEvaluationVerdict(
                decision=decision,
                is_approved_to_sign=True,
                signature_token=sig,
                diagnostic_reason=reason,
                tx_id=payload.tx_id,
                remaining_daily_allowance=self._calc_remaining_allowance(),
            )

        if decision == SigningDecisionStatus.REQUIRE_HITL_STEP_UP:
            self._metrics.hitl_stepped_up_total += 1
            self._pending_hitl_txs[payload.tx_id] = payload
            return SigningEvaluationVerdict(
                decision=decision,
                is_approved_to_sign=False,
                signature_token=None,
                diagnostic_reason=reason,
                tx_id=payload.tx_id,
                remaining_daily_allowance=self._calc_remaining_allowance(),
            )

        if decision == SigningDecisionStatus.REJECTED_QUOTA_EXCEEDED:
            self._metrics.rejected_quota_total += 1
        elif decision == SigningDecisionStatus.REJECTED_UNTRUSTED_RECIPIENT:
            self._metrics.rejected_untrusted_total += 1

        return SigningEvaluationVerdict(
            decision=decision,
            is_approved_to_sign=False,
            signature_token=None,
            diagnostic_reason=reason,
            tx_id=payload.tx_id,
            remaining_daily_allowance=self._calc_remaining_allowance(),
        )

    def approve_stepped_up_tx(
        self, tx_id: str, approver_note: str = "Human Approved"
    ) -> SigningEvaluationVerdict | None:
        """Explicitly approve a pending step-up transaction following human verification."""
        if self._is_kill_switch_active:
            self._metrics.kill_switch_blocked_total += 1
            return SigningEvaluationVerdict(
                decision=SigningDecisionStatus.FROZEN_BY_KILL_SWITCH,
                is_approved_to_sign=False,
                signature_token=None,
                diagnostic_reason=f"Emergency kill-switch active: {self._kill_switch_reason}",
                tx_id=tx_id,
                remaining_daily_allowance=self._calc_remaining_allowance(),
            )

        payload = self._pending_hitl_txs.pop(tx_id, None)
        if payload is None:
            return None

        self._current_daily_spent += payload.amount
        self._metrics.silent_signed_total += 1
        sig = self._generate_signature(payload)

        return SigningEvaluationVerdict(
            decision=SigningDecisionStatus.SILENT_AUTHORIZED,
            is_approved_to_sign=True,
            signature_token=sig,
            diagnostic_reason=f"Step-up HITL approved: {approver_note}",
            tx_id=payload.tx_id,
            remaining_daily_allowance=self._calc_remaining_allowance(),
        )

    def reject_stepped_up_tx(self, tx_id: str) -> bool:
        """Reject and remove a pending step-up transaction."""
        return self._pending_hitl_txs.pop(tx_id, None) is not None

    def list_pending_hitl_txs(self) -> tuple[TransactionPayload, ...]:
        """Return all transactions currently awaiting human confirmation."""
        return tuple(self._pending_hitl_txs.values())

    def _calc_remaining_allowance(self) -> float:
        limit = self._quota_guard.config.daily_cumulative_limit
        return max(0.0, limit - self._current_daily_spent)

    def _generate_signature(self, payload: TransactionPayload) -> str:
        """Generate high-entropy cryptographic signature mock from airgapped enclave."""
        message = (
            f"{payload.tx_id}:{payload.recipient}:{payload.amount:.4f}:"
            f"{payload.currency}:{payload.chain_or_network}:{time.time():.4f}"
        ).encode()
        return hmac.new(self._mock_seed, message, hashlib.sha256).hexdigest()
