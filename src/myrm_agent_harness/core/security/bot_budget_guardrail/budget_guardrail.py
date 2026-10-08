"""Autonomous Bot Budget Guardrail and Token Ceiling Circuit Breaker implementation.

Provides isolated budget sandboxes for autonomous background bots and channel bots,
guarding main user interactive quota against runaway loop consumption.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Sequence

from myrm_agent_harness.core.security.bot_budget_guardrail.types import (
    BotBudgetQuota,
    BudgetConsumeResult,
    CircuitBreakerState,
)

logger = logging.getLogger(__name__)


class AutonomousBotBudgetGuardrail:
    """Thread-safe circuit breaker and budget isolation manager for autonomous bots."""

    def __init__(self) -> None:
        self._quotas: dict[str, BotBudgetQuota] = {}
        self._lock: threading.Lock = threading.Lock()

    def register_bot_quota(self, quota: BotBudgetQuota) -> None:
        """Register or update an autonomous bot's budget sandbox."""
        with self._lock:
            quota.last_updated_at = time.time()
            self._quotas[quota.bot_id] = quota

    def get_quota_status(self, bot_id: str) -> BotBudgetQuota | None:
        """Retrieve quota status for a specific bot."""
        with self._lock:
            quota = self._quotas.get(bot_id)
            if quota is None:
                return None
            return self._clone_quota(quota)

    def list_all_quotas(self) -> Sequence[BotBudgetQuota]:
        """List all active bot budget sandboxes."""
        with self._lock:
            return [self._clone_quota(q) for q in self._quotas.values()]

    def consume_budget(
        self,
        bot_id: str,
        tokens: int,
        cost_usd: float,
    ) -> BudgetConsumeResult:
        """Evaluate and deduct consumption against an isolated budget sandbox.

        Enforces tiered circuit breaker:
        - < 80%: CLOSED (healthy)
        - >= 80%: HALF_OPEN (soft warning)
        - >= 100%: OPEN_FROZEN (hard ceiling tripped, execution refused)
        """
        with self._lock:
            quota = self._quotas.get(bot_id)
            if quota is None:
                return BudgetConsumeResult(
                    allowed=False,
                    bot_id=bot_id,
                    state=CircuitBreakerState.OPEN_FROZEN,
                    current_used_tokens=0,
                    current_used_cost_usd=0.0,
                    tokens_remaining=0,
                    cost_remaining_usd=0.0,
                    rejection_reason=f"Bot '{bot_id}' is not registered in any budget sandbox (fail-closed).",
                )

            # Check if circuit breaker is already tripped
            if quota.state == CircuitBreakerState.OPEN_FROZEN:
                rem_tok = max(0, quota.token_ceiling - quota.used_tokens)
                rem_cost = max(0.0, quota.cost_ceiling_usd - quota.used_cost_usd)
                return BudgetConsumeResult(
                    allowed=False,
                    bot_id=bot_id,
                    state=CircuitBreakerState.OPEN_FROZEN,
                    current_used_tokens=quota.used_tokens,
                    current_used_cost_usd=quota.used_cost_usd,
                    tokens_remaining=rem_tok,
                    cost_remaining_usd=rem_cost,
                    rejection_reason=(
                        f"Circuit breaker is OPEN_FROZEN for bot '{bot_id}'. "
                        "Execution suspended to prevent runaway consumption."
                    ),
                )

            projected_tokens = quota.used_tokens + tokens
            projected_cost = quota.used_cost_usd + cost_usd

            # Hard ceiling breach check
            if projected_tokens > quota.token_ceiling or projected_cost > quota.cost_ceiling_usd:
                quota.state = CircuitBreakerState.OPEN_FROZEN
                quota.frozen_at = time.time()
                quota.last_updated_at = time.time()
                rem_tok = max(0, quota.token_ceiling - quota.used_tokens)
                rem_cost = max(0.0, quota.cost_ceiling_usd - quota.used_cost_usd)
                logger.warning(
                    "Bot '%s' tripped circuit breaker! Projected tokens: %d/%d, cost: $%.4f/$%.4f",
                    bot_id,
                    projected_tokens,
                    quota.token_ceiling,
                    projected_cost,
                    quota.cost_ceiling_usd,
                )
                return BudgetConsumeResult(
                    allowed=False,
                    bot_id=bot_id,
                    state=CircuitBreakerState.OPEN_FROZEN,
                    current_used_tokens=quota.used_tokens,
                    current_used_cost_usd=quota.used_cost_usd,
                    tokens_remaining=rem_tok,
                    cost_remaining_usd=rem_cost,
                    rejection_reason="Exceeded token or cost ceiling. Hard ceiling circuit breaker tripped.",
                )

            # Deduct consumption
            quota.used_tokens = projected_tokens
            quota.used_cost_usd = projected_cost
            quota.last_updated_at = time.time()

            # Warning threshold check (>= 80%)
            token_ratio = (quota.used_tokens / quota.token_ceiling) if quota.token_ceiling > 0 else 0.0
            cost_ratio = (quota.used_cost_usd / quota.cost_ceiling_usd) if quota.cost_ceiling_usd > 0 else 0.0
            if token_ratio >= quota.warning_threshold or cost_ratio >= quota.warning_threshold:
                quota.state = CircuitBreakerState.HALF_OPEN
            else:
                quota.state = CircuitBreakerState.CLOSED

            rem_tok = max(0, quota.token_ceiling - quota.used_tokens)
            rem_cost = max(0.0, quota.cost_ceiling_usd - quota.used_cost_usd)

            return BudgetConsumeResult(
                allowed=True,
                bot_id=bot_id,
                state=quota.state,
                current_used_tokens=quota.used_tokens,
                current_used_cost_usd=quota.used_cost_usd,
                tokens_remaining=rem_tok,
                cost_remaining_usd=rem_cost,
                rejection_reason=None,
            )

    def refuel_quota(
        self,
        bot_id: str,
        additional_tokens: int = 0,
        additional_cost_usd: float = 0.0,
        reset_state: bool = True,
    ) -> BotBudgetQuota:
        """Increase quota ceilings and optionally unfreeze a tripped bot circuit breaker."""
        with self._lock:
            quota = self._quotas.get(bot_id)
            if quota is None:
                raise KeyError(f"Bot '{bot_id}' is not registered.")

            quota.token_ceiling += max(0, additional_tokens)
            quota.cost_ceiling_usd += max(0.0, additional_cost_usd)
            quota.last_updated_at = time.time()

            if reset_state:
                # Re-evaluate state after refuel
                token_ratio = (quota.used_tokens / quota.token_ceiling) if quota.token_ceiling > 0 else 0.0
                cost_ratio = (quota.used_cost_usd / quota.cost_ceiling_usd) if quota.cost_ceiling_usd > 0 else 0.0
                if token_ratio < 1.0 and cost_ratio < 1.0:
                    quota.frozen_at = None
                    if token_ratio >= quota.warning_threshold or cost_ratio >= quota.warning_threshold:
                        quota.state = CircuitBreakerState.HALF_OPEN
                    else:
                        quota.state = CircuitBreakerState.CLOSED

            return self._clone_quota(quota)

    def reset_all(self) -> None:
        """Clear all registered quotas (used for test isolation)."""
        with self._lock:
            self._quotas.clear()

    @staticmethod
    def _clone_quota(q: BotBudgetQuota) -> BotBudgetQuota:
        return BotBudgetQuota(
            bot_id=q.bot_id,
            bot_name=q.bot_name,
            sandbox_mode=q.sandbox_mode,
            token_ceiling=q.token_ceiling,
            cost_ceiling_usd=q.cost_ceiling_usd,
            used_tokens=q.used_tokens,
            used_cost_usd=q.used_cost_usd,
            warning_threshold=q.warning_threshold,
            state=q.state,
            frozen_at=q.frozen_at,
            last_updated_at=q.last_updated_at,
        )
