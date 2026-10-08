"""Deterministic pre-flight dry-run simulator for financial transactions."""

from __future__ import annotations

from .types import TransactionIntent, TransactionSimulationResult


class TransactionSimulator:
    """Simulates market execution and calculates slippage, fee estimates, and principal exposure."""

    def simulate(self, intent: TransactionIntent) -> TransactionSimulationResult:
        """Run pre-flight deterministic sandbox simulation on transaction intent."""
        notes: list[str] = []

        # 1. Base fee estimation (fixed network estimate or proportion)
        base_fee = max(0.5, round(intent.amount_usd * 0.001, 2))
        notes.append(f"Estimated network/protocol fee: ${base_fee:.2f}")

        # 2. Market impact & estimated slippage (bps)
        # Larger USD volume leads to deeper market impact simulation
        impact_bps = 5  # baseline 0.05%
        if intent.amount_usd > 1000.0:
            impact_bps += int((intent.amount_usd - 1000.0) / 100.0) * 10
        elif intent.amount_usd > 200.0:
            impact_bps += int((intent.amount_usd - 200.0) / 50.0) * 5

        estimated_slippage = min(1000, impact_bps)
        notes.append(f"Simulated market depth impact: {estimated_slippage} bps")

        # 3. Maximum potential loss calculation
        slippage_loss = intent.amount_usd * (intent.slippage_tolerance_bps / 10000.0)
        max_loss = round(base_fee + slippage_loss, 2)
        notes.append(f"Maximum downside bound (fee + slippage max): ${max_loss:.2f}")

        # 4. Composite risk score computation (0-100)
        risk = 10
        if intent.amount_usd > 500.0:
            risk += 40
        elif intent.amount_usd > 100.0:
            risk += 20

        if estimated_slippage > 150:
            risk += 35
        elif estimated_slippage > 50:
            risk += 15

        if base_fee > intent.max_fee_limit and intent.max_fee_limit > 0:
            risk += 30
            notes.append("Fee exceeds target maximum fee limit threshold.")

        risk_score = min(100, max(0, risk))

        return TransactionSimulationResult(
            is_simulated=True,
            estimated_gas_or_fee=base_fee,
            estimated_slippage_bps=estimated_slippage,
            max_loss_usd=max_loss,
            risk_score=risk_score,
            simulation_notes=notes,
        )
