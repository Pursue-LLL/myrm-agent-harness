"""Circuit breaker guard evaluating risk exposure and financial kill switches.

[INPUT]
- TradingCircuitBreakers policy thresholds and telemetry metrics (loss %, position %, exposure %).

[OUTPUT]
- Decision tuple indicating whether capital operations must be frozen and reason.

[POS]
- Quantitative risk gate preventing catastrophic autonomous financial loss.
"""

from __future__ import annotations

from myrm_agent_harness.core.security.commerce_dispute_escrow.types import (
    TradingCircuitBreakers,
)


class CommerceCircuitBreakerEvaluator:
    """Evaluates trading risk metrics against circuit breaker thresholds."""

    @staticmethod
    def evaluate(
        circuit_breakers: TradingCircuitBreakers | None,
        current_position_pct: float = 0.0,
        current_daily_loss_pct: float = 0.0,
        current_open_exposure_pct: float = 0.0,
        emergency_trigger: bool = False,
    ) -> tuple[bool, str | None]:
        """Evaluate current trading state against quantitative circuit breakers.

        Args:
            circuit_breakers: Quantitative threshold configuration.
            current_position_pct: Current single position size percentage.
            current_daily_loss_pct: Realized and unrealized daily loss percentage.
            current_open_exposure_pct: Total aggregate capital exposure percentage.
            emergency_trigger: Explicit emergency halt request.

        Returns:
            Tuple of (triggered: bool, reason: str | None).
        """
        if circuit_breakers is None:
            if emergency_trigger:
                return True, "Emergency kill switch manually activated."
            return False, None

        if emergency_trigger or circuit_breakers.emergency_kill_switch_active:
            return True, "Emergency kill switch active: all trading halted."

        if current_position_pct > circuit_breakers.max_position_pct:
            return True, (
                f"Position limit breached: {current_position_pct:.2f}% "
                f"> {circuit_breakers.max_position_pct:.2f}%"
            )

        if current_daily_loss_pct > circuit_breakers.max_daily_loss_pct:
            return True, (
                f"Daily loss limit breached: {current_daily_loss_pct:.2f}% "
                f"> {circuit_breakers.max_daily_loss_pct:.2f}%"
            )

        if current_open_exposure_pct > circuit_breakers.max_open_exposure_pct:
            return True, (
                f"Open exposure limit breached: {current_open_exposure_pct:.2f}% "
                f"> {circuit_breakers.max_open_exposure_pct:.2f}%"
            )

        return False, None
