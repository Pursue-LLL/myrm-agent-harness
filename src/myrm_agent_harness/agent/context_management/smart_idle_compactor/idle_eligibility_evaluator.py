"""Idle eligibility evaluator for opportunistic prompt cache pre-compaction.

Evaluates idle duration, token budgets, and provider cache TTL windows to seize
the 0.1x cache read discount before upstream eviction occurs.

[INPUT]
- agent.context_management.smart_idle_compactor.idle_compactor_types::CacheWindowStatus, IdleCompactionAction,
  IdleCompactionEvaluation, IdleCompactorConfig (POS: Data contracts and type definitions for smart idle cache
  auto-compaction.)

[OUTPUT]
- IdleEligibilityEvaluator: Evaluates whether an idle session qualifies for opportunistic background
  pre-compaction.

[POS]
Idle eligibility evaluator for opportunistic prompt cache pre-compaction.
"""

from __future__ import annotations

import time

from .idle_compactor_types import (
    CacheWindowStatus,
    IdleCompactionAction,
    IdleCompactionEvaluation,
    IdleCompactorConfig,
)


class IdleEligibilityEvaluator:
    """Evaluates whether an idle session qualifies for opportunistic background pre-compaction."""

    def __init__(self, config: IdleCompactorConfig | None = None) -> None:
        self.config = config or IdleCompactorConfig()

    def evaluate(
        self,
        session_id: str,
        current_tokens: int,
        last_turn_timestamp_epoch: float,
        current_timestamp_epoch: float | None = None,
    ) -> IdleCompactionEvaluation:
        """Assess the session's prompt cache lifespan and determine if compaction is opportune."""
        now = current_timestamp_epoch if current_timestamp_epoch is not None else time.time()
        idle_seconds = max(0.0, now - last_turn_timestamp_epoch)

        hot_cost = current_tokens * self.config.cache_hit_rate_multiplier
        cold_cost = current_tokens * self.config.full_prefill_multiplier
        potential_savings = 1.0 - (hot_cost / cold_cost) if cold_cost > 0 else 0.0

        # 1. Check token threshold
        if current_tokens < self.config.min_token_threshold:
            return IdleCompactionEvaluation(
                session_id=session_id,
                current_tokens=current_tokens,
                idle_duration_seconds=idle_seconds,
                cache_status=CacheWindowStatus.HOT_FRESH,
                action=IdleCompactionAction.SKIP_BELOW_TOKEN_BUDGET,
                estimated_hot_compaction_cost_units=hot_cost,
                estimated_cold_compaction_cost_units=cold_cost,
                potential_savings_ratio=potential_savings,
                reason=(
                    f"Current tokens ({current_tokens}) are below threshold "
                    f"({self.config.min_token_threshold}); compaction not needed."
                ),
            )

        # 2. Check if cache has already expired
        if idle_seconds > self.config.cache_ttl_seconds:
            return IdleCompactionEvaluation(
                session_id=session_id,
                current_tokens=current_tokens,
                idle_duration_seconds=idle_seconds,
                cache_status=CacheWindowStatus.EXPIRED_COLD,
                action=IdleCompactionAction.SKIP_CACHE_ALREADY_EXPIRED,
                estimated_hot_compaction_cost_units=cold_cost,  # already degraded to cold
                estimated_cold_compaction_cost_units=cold_cost,
                potential_savings_ratio=0.0,
                reason=(
                    f"Idle duration ({idle_seconds:.1f}s) exceeded cache TTL "
                    f"({self.config.cache_ttl_seconds}s). Provider KV cache already evicted."
                ),
            )

        # 3. Check if too early (user may still be actively typing or reading)
        if idle_seconds < self.config.idle_trigger_min_seconds:
            return IdleCompactionEvaluation(
                session_id=session_id,
                current_tokens=current_tokens,
                idle_duration_seconds=idle_seconds,
                cache_status=CacheWindowStatus.HOT_FRESH,
                action=IdleCompactionAction.SKIP_TOO_EARLY,
                estimated_hot_compaction_cost_units=hot_cost,
                estimated_cold_compaction_cost_units=cold_cost,
                potential_savings_ratio=potential_savings,
                reason=(
                    f"Idle duration ({idle_seconds:.1f}s) has not reached minimum inactivity "
                    f"window ({self.config.idle_trigger_min_seconds}s). Active typing likely."
                ),
            )

        # 4. Golden opportunistic window reached: 30 - 50 minutes of idle inactivity
        return IdleCompactionEvaluation(
            session_id=session_id,
            current_tokens=current_tokens,
            idle_duration_seconds=idle_seconds,
            cache_status=CacheWindowStatus.OPPORTUNISTIC_EXPIRING_SOON,
            action=IdleCompactionAction.TRIGGER_OPPORTUNISTIC,
            estimated_hot_compaction_cost_units=hot_cost,
            estimated_cold_compaction_cost_units=cold_cost,
            potential_savings_ratio=potential_savings,
            reason=(
                f"Opportunistic window active! Session idle for {idle_seconds / 60.0:.1f} mins. "
                f"Upstream KV cache is hot (0.1x rate). Pre-compaction saves {potential_savings * 100:.0f}% cost."
            ),
        )
