"""Tokenomics Downgrade Gate providing graceful model fallback upon budget thresholds."""

from __future__ import annotations

from .types import DowngradeGateSpec, DowngradeGateStatus


class DowngradeGate:
    """Manages soft/hard spending thresholds and dynamically shifts execution

    to economical fallback models to avert session aborts.
    """

    def __init__(self, spec: DowngradeGateSpec | None = None) -> None:
        self._spec: DowngradeGateSpec = spec or DowngradeGateSpec()
        self._session_tokens: dict[str, int] = {}
        self._session_costs: dict[str, float] = {}

    @property
    def spec(self) -> DowngradeGateSpec:
        """Access underlying threshold specifications."""
        return self._spec

    def record_usage(
        self,
        session_id: str,
        additional_tokens: int,
        additional_cost: float,
    ) -> DowngradeGateStatus:
        """Record usage delta and evaluate downgrade gate state."""
        clean_sess = session_id.strip()
        new_tokens = self._session_tokens.get(clean_sess, 0) + additional_tokens
        new_cost = self._session_costs.get(clean_sess, 0.0) + additional_cost

        self._session_tokens[clean_sess] = new_tokens
        self._session_costs[clean_sess] = new_cost

        return self.get_status(clean_sess)

    def get_status(self, session_id: str) -> DowngradeGateStatus:
        """Query current model routing and threshold status for a session."""
        clean_sess = session_id.strip()
        tokens = self._session_tokens.get(clean_sess, 0)
        cost = self._session_costs.get(clean_sess, 0.0)

        # 1. Hard limit check: hard block
        if cost >= self._spec.hard_limit_cost:
            return DowngradeGateStatus(
                is_downgraded=True,
                is_hard_blocked=True,
                active_model=self._spec.fallback_model,
                total_tokens=tokens,
                total_cost=cost,
                message=(
                    f"Hard limit of ${self._spec.hard_limit_cost:.2f} reached "
                    f"(accumulated: ${cost:.2f}); operation suspended."
                ),
            )

        # 2. Soft limit check: graceful downgrade to fallback model
        is_soft_exceeded = (
            tokens >= self._spec.soft_limit_tokens
            or cost >= self._spec.soft_limit_cost
        )
        if is_soft_exceeded:
            return DowngradeGateStatus(
                is_downgraded=True,
                is_hard_blocked=False,
                active_model=self._spec.fallback_model,
                total_tokens=tokens,
                total_cost=cost,
                message=(
                    f"Soft budget threshold reached ({tokens} tokens, ${cost:.2f}); "
                    f"gracefully downgraded to economical model '{self._spec.fallback_model}'."
                ),
            )

        # 3. Normal operating state
        return DowngradeGateStatus(
            is_downgraded=False,
            is_hard_blocked=False,
            active_model=self._spec.primary_model,
            total_tokens=tokens,
            total_cost=cost,
            message="Within nominal budget thresholds; running on primary model.",
        )

    def reset_session(self, session_id: str) -> None:
        """Reset budget counters for a concluded session."""
        clean_sess = session_id.strip()
        self._session_tokens.pop(clean_sess, None)
        self._session_costs.pop(clean_sess, None)
