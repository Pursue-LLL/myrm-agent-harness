"""Anti-silent-downgrade fingerprint monitor and session budget watermark guard.

[INPUT]
- arbitrage_types: BudgetWatermarkLevel, BudgetWatermarkStatus,
  ModelFingerprintProfile, WorkspaceArbitrageConfig.

[OUTPUT]
- AntiDowngradeBudgetGuard: Tracks vendor model fingerprint drift and enforces
  soft/hard financial budget watermark guards with local fallback.

[POS]
- Sub-package: myrm_agent_harness.agent.context_management.workspace_arbitrage
- Module: anti_downgrade_budget_guard.py
"""

from typing import Dict, List, Optional
from myrm_agent_harness.agent.context_management.workspace_arbitrage.arbitrage_types import (
    BudgetWatermarkLevel,
    BudgetWatermarkStatus,
    ModelFingerprintProfile,
    WorkspaceArbitrageConfig,
)


class AntiDowngradeBudgetGuard:
    """Monitors model provider fingerprint stability and enforces session budget limits."""

    def __init__(self, config: Optional[WorkspaceArbitrageConfig] = None) -> None:
        self._config = config or WorkspaceArbitrageConfig()
        # model_name -> list of historical fingerprint profiles
        self._fingerprint_history: Dict[str, List[ModelFingerprintProfile]] = {}
        # session_id -> accumulated cost in USD
        self._session_costs: Dict[str, float] = {}
        # session_id -> custom budget limit if overridden
        self._session_limits: Dict[str, float] = {}

    def record_model_call(
        self,
        model_name: str,
        system_fingerprint: str,
        latency_ms: float,
        output_token_count: int,
        is_truncated: bool = False,
    ) -> ModelFingerprintProfile:
        """Inspects and logs provider response metadata to detect silent model degradation.

        Args:
            model_name: Model identifier claimed by provider.
            system_fingerprint: Provider fingerprint string.
            latency_ms: Turn response duration.
            output_token_count: Number of tokens generated.
            is_truncated: Whether output was cut off unexpectedly.

        Returns:
            A ModelFingerprintProfile with drift diagnostic flags.
        """
        history = self._fingerprint_history.setdefault(model_name, [])
        detected_drift = False

        if history:
            last_profile = history[-1]
            # Drift detected if fingerprint changed AND latency spiked abnormally (> 2.5x)
            fingerprint_changed = (
                bool(system_fingerprint)
                and bool(last_profile.system_fingerprint)
                and system_fingerprint != last_profile.system_fingerprint
            )
            latency_spiked = (
                last_profile.latency_ms > 0
                and latency_ms >= last_profile.latency_ms * 2.5
            )
            if fingerprint_changed and (latency_spiked or is_truncated):
                detected_drift = True

        profile = ModelFingerprintProfile(
            model_name=model_name,
            system_fingerprint=system_fingerprint,
            latency_ms=latency_ms,
            output_token_count=output_token_count,
            is_truncated=is_truncated,
            detected_drift=detected_drift,
        )
        history.append(profile)
        return profile

    def track_spending(
        self, session_id: str, cost_usd: float
    ) -> BudgetWatermarkStatus:
        """Accumulates session spending and checks watermark thresholds.

        Args:
            session_id: Active session identifier.
            cost_usd: Cost added in this turn.

        Returns:
            Current BudgetWatermarkStatus.
        """
        current_spent = self._session_costs.get(session_id, 0.0) + cost_usd
        self._session_costs[session_id] = round(current_spent, 6)
        limit = self._session_limits.get(
            session_id, self._config.default_session_budget_usd
        )

        ratio = current_spent / limit if limit > 0 else 1.0
        percentage = round(ratio * 100.0, 2)

        if ratio >= self._config.hard_budget_fuse_ratio:
            level = BudgetWatermarkLevel.HARD_FUSED_100
            enforce_local = True
        elif ratio >= self._config.soft_budget_warning_ratio:
            level = BudgetWatermarkLevel.SOFT_WARNING_80
            enforce_local = False
        else:
            level = BudgetWatermarkLevel.NORMAL
            enforce_local = False

        return BudgetWatermarkStatus(
            session_id=session_id,
            budget_limit_usd=limit,
            consumed_usd=round(current_spent, 6),
            consumption_percentage=percentage,
            watermark_level=level,
            enforce_fallback_to_local=enforce_local,
        )

    def set_session_limit(self, session_id: str, limit_usd: float) -> None:
        """Sets a custom budget ceiling for a specific session."""
        self._session_limits[session_id] = max(0.0001, limit_usd)

    def get_watermark_status(self, session_id: str) -> BudgetWatermarkStatus:
        """Retrieves current watermark status without adding spending."""
        return self.track_spending(session_id, 0.0)
