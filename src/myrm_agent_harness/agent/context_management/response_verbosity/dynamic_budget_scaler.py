# [INPUT]: ResponseVerbosityLevel, VerbosityBudgetConfig
# [OUTPUT]: DynamicBudgetScaler
# [POS]: agent/context_management/response_verbosity/dynamic_budget_scaler.py

"""Dynamic token budget scaler adapting physical generation limits to verbosity requirements.

[INPUT]
- ResponseVerbosityLevel: Active verbosity tier.
- VerbosityBudgetConfig: Configuration specifying token limits per tier.

[OUTPUT]
- DynamicBudgetScaler: Computes recommended max_tokens and penalty parameters.

[POS]
Resource tuning layer in response verbosity subsystem physically reducing latency and cost.
"""

from __future__ import annotations

from .verbosity_types import ResponseVerbosityLevel, VerbosityBudgetConfig


class DynamicBudgetScaler:
    """Scales physical token allowances and model hyper-parameters according to target verbosity."""

    def __init__(self, config: VerbosityBudgetConfig | None = None) -> None:
        self._config = config or VerbosityBudgetConfig()

    def scale_budget(
        self,
        level: ResponseVerbosityLevel,
        model_hard_ceiling: int | None = None,
    ) -> tuple[int, float]:
        """Compute (recommended_max_tokens, presence_penalty) for the given verbosity tier.

        Returns:
            A tuple of (recommended_max_tokens, presence_penalty).
        """
        if level == ResponseVerbosityLevel.LOW:
            raw_tokens = self._config.low_max_tokens
            presence_penalty = 0.1  # Slight penalty discouraging repetitive rambling
        elif level == ResponseVerbosityLevel.HIGH:
            raw_tokens = self._config.high_max_tokens
            presence_penalty = 0.0
        else:
            raw_tokens = self._config.medium_max_tokens
            presence_penalty = 0.0

        if not self._config.enforce_token_budget_clamping:
            return raw_tokens, presence_penalty

        # Clamp against model ceiling if provided
        if model_hard_ceiling is not None and model_hard_ceiling > 0:
            final_tokens = min(raw_tokens, model_hard_ceiling)
        else:
            final_tokens = raw_tokens

        return final_tokens, presence_penalty
