"""Autonomous Financial Execution Safety Guard enforcing budget limits and slippage breakers."""

from __future__ import annotations

import time

from .transaction_simulator import TransactionSimulator
from .types import (
    FinancialBudgetConfig,
    FinancialDecision,
    FinancialRiskTier,
    TransactionIntent,
    TransactionSecurityCard,
    TransactionSimulationResult,
)


class FinancialSafetyGuard:
    """Pre-flight safety gate and circuit breaker for financial transactions."""

    def __init__(
        self,
        config: FinancialBudgetConfig | None = None,
        simulator: TransactionSimulator | None = None,
    ) -> None:
        self._config = config or FinancialBudgetConfig()
        self._simulator = simulator or TransactionSimulator()
        self._daily_spent_usd: float = 0.0
        self._last_reset_time: float = time.time()
        self._evaluated_cards: list[TransactionSecurityCard] = []
        self._pending_approvals: dict[str, TransactionSecurityCard] = {}

    @property
    def config(self) -> FinancialBudgetConfig:
        return self._config

    @property
    def daily_spent_usd(self) -> float:
        return self._daily_spent_usd

    def update_config(self, new_config: FinancialBudgetConfig) -> None:
        """Update spending thresholds and circuit breaker configuration."""
        self._config = new_config

    def reset_daily_spent(self) -> None:
        """Manually or periodically reset daily spending counter."""
        self._daily_spent_usd = 0.0
        self._last_reset_time = time.time()

    def _determine_risk_tier(self, score: int) -> FinancialRiskTier:
        if score < 30:
            return FinancialRiskTier.LOW
        if score < 60:
            return FinancialRiskTier.MEDIUM
        if score < 80:
            return FinancialRiskTier.HIGH
        return FinancialRiskTier.CRITICAL

    def evaluate_transaction(self, intent: TransactionIntent) -> TransactionSecurityCard:
        """Run pre-flight simulation and evaluate budget and slippage breaker criteria."""
        now = time.time()
        simulation: TransactionSimulationResult = self._simulator.simulate(intent)
        risk_tier = self._determine_risk_tier(simulation.risk_score)

        remaining_budget = max(0.0, self._config.daily_limit_usd - self._daily_spent_usd)
        rejection_reason: str | None = None
        decision: FinancialDecision
        requires_manual_approval = False

        # 1. Slippage Circuit Breaker Check
        if simulation.estimated_slippage_bps > self._config.max_allowed_slippage_bps:
            decision = FinancialDecision.REJECT_BREAKER
            rejection_reason = (
                f"Slippage circuit breaker triggered: estimated slippage "
                f"{simulation.estimated_slippage_bps} bps exceeds max allowed "
                f"{self._config.max_allowed_slippage_bps} bps."
            )
        # 2. Critical Risk Score Breaker Check
        elif simulation.risk_score >= self._config.critical_risk_score_threshold:
            decision = FinancialDecision.REJECT_BREAKER
            rejection_reason = (
                f"Risk score circuit breaker triggered: composite score {simulation.risk_score} "
                f"meets or exceeds critical threshold {self._config.critical_risk_score_threshold}."
            )
        # 3. Single Transaction Limit Check
        elif intent.amount_usd > self._config.single_tx_limit_usd:
            decision = FinancialDecision.ASK_CONFIRMATION
            requires_manual_approval = True
            rejection_reason = (
                f"Single transaction amount (${intent.amount_usd:.2f}) exceeds auto-approval "
                f"limit (${self._config.single_tx_limit_usd:.2f})."
            )
        # 4. Daily Spending Budget Limit Check
        elif (self._daily_spent_usd + intent.amount_usd) > self._config.daily_limit_usd:
            decision = FinancialDecision.ASK_CONFIRMATION
            requires_manual_approval = True
            rejection_reason = (
                f"Transaction amount (${intent.amount_usd:.2f}) exceeds remaining daily "
                f"budget (${remaining_budget:.2f})."
            )
        # 5. Clean Approval
        else:
            decision = FinancialDecision.APPROVE
            self._daily_spent_usd = round(self._daily_spent_usd + intent.amount_usd, 2)
            remaining_budget = max(0.0, self._config.daily_limit_usd - self._daily_spent_usd)

        card = TransactionSecurityCard(
            tx_id=intent.tx_id,
            decision=decision,
            risk_tier=risk_tier,
            intent=intent,
            simulation=simulation,
            daily_spent_usd=self._daily_spent_usd,
            remaining_daily_budget_usd=remaining_budget,
            requires_manual_approval=requires_manual_approval,
            rejection_reason=rejection_reason,
            created_at=now,
        )

        self._evaluated_cards.append(card)
        if decision == FinancialDecision.ASK_CONFIRMATION:
            self._pending_approvals[intent.tx_id] = card

        return card

    def approve_manually(self, tx_id: str) -> TransactionSecurityCard | None:
        """Manually approve a transaction suspended for confirmation."""
        pending = self._pending_approvals.get(tx_id)
        if pending is None:
            return None

        # Execute manual approval: update state and accumulate budget
        self._daily_spent_usd = round(self._daily_spent_usd + pending.intent.amount_usd, 2)
        remaining = max(0.0, self._config.daily_limit_usd - self._daily_spent_usd)

        approved_card = TransactionSecurityCard(
            tx_id=pending.tx_id,
            decision=FinancialDecision.APPROVE,
            risk_tier=pending.risk_tier,
            intent=pending.intent,
            simulation=pending.simulation,
            daily_spent_usd=self._daily_spent_usd,
            remaining_daily_budget_usd=remaining,
            requires_manual_approval=False,
            rejection_reason=None,
            created_at=time.time(),
        )

        del self._pending_approvals[tx_id]
        self._evaluated_cards.append(approved_card)
        return approved_card

    def get_history(self, limit: int = 50) -> list[TransactionSecurityCard]:
        """Fetch transaction security inspection cards history."""
        if limit <= 0:
            return list(self._evaluated_cards)
        return list(self._evaluated_cards[-limit:])
