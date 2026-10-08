"""
[POS] src/myrm_agent_harness/core/security/autonomous_signing_airgap/facade.py
[INPUT] types, quota_guard, signing_delegate
[OUTPUT] AutonomousSigningAirgapFacade
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from .quota_guard import PayloadAstInspectorAndQuotaGuard
from .signing_delegate import KeyringAirgapSigningDelegate
from .types import (
    SigningEvaluationVerdict,
    SigningQuotaConfig,
    TransactionPayload,
    WalletAirgapMetrics,
)


class AutonomousSigningAirgapFacade:
    """Unified entrypoint for headless autonomous signing sandbox and keyring airgap."""

    def __init__(
        self,
        quota_config: SigningQuotaConfig | None = None,
        mock_keyring_seed: str = "myrm-local-keyring-airgap-seed-2026",
    ) -> None:
        self._metrics = WalletAirgapMetrics()
        self._quota_guard = PayloadAstInspectorAndQuotaGuard(config=quota_config)
        self._delegate = KeyringAirgapSigningDelegate(
            quota_guard=self._quota_guard,
            metrics=self._metrics,
            mock_keyring_seed=mock_keyring_seed,
        )

    @property
    def metrics(self) -> WalletAirgapMetrics:
        """Shared operational metrics."""
        return self._metrics

    @property
    def is_kill_switch_active(self) -> bool:
        """Whether the wallet signing kill-switch is currently engaged."""
        return self._delegate.is_kill_switch_active

    @property
    def kill_switch_reason(self) -> str:
        """Reason provided when kill-switch was triggered."""
        return self._delegate.kill_switch_reason

    @property
    def current_daily_spent(self) -> float:
        """Cumulative expenditure recorded in active window."""
        return self._delegate.current_daily_spent

    def evaluate_and_sign(
        self, payload: TransactionPayload
    ) -> SigningEvaluationVerdict:
        """Assert payload against airgap kill-switch and quota guard, signing if authorized."""
        return self._delegate.evaluate_and_sign(payload)

    def approve_stepped_up_tx(
        self, tx_id: str, approver_note: str = "Human Approved"
    ) -> SigningEvaluationVerdict | None:
        """Approve and sign a pending transaction held by step-up HITL."""
        return self._delegate.approve_stepped_up_tx(tx_id, approver_note)

    def reject_stepped_up_tx(self, tx_id: str) -> bool:
        """Reject and remove a pending step-up transaction."""
        return self._delegate.reject_stepped_up_tx(tx_id)

    def list_pending_hitl_txs(self) -> tuple[TransactionPayload, ...]:
        """List transactions awaiting human confirmation."""
        return self._delegate.list_pending_hitl_txs()

    def trigger_kill_switch(self, reason: str = "Emergency Freeze Triggered") -> None:
        """Activate physical emergency wallet kill-switch."""
        self._delegate.trigger_kill_switch(reason=reason)

    def release_kill_switch(self) -> None:
        """Disengage kill-switch and restore signing operation."""
        self._delegate.release_kill_switch()

    def update_quota_config(self, config: SigningQuotaConfig) -> None:
        """Update quota rules dynamically."""
        self._quota_guard.update_config(config)

    def get_quota_config(self) -> SigningQuotaConfig:
        """Retrieve active quota configuration."""
        return self._quota_guard.config

    def reset_daily_quota(self, starting_amount: float = 0.0) -> None:
        """Reset daily cumulative expenditure counter."""
        self._delegate.reset_daily_quota(starting_amount)
