"""Core calculator isolating incremental run token usage from legacy historical context.

Eliminates repetitive billing over inherited session history upon resumption while
accurately accounting for prompt cache discounts.
"""

from __future__ import annotations

from .resumed_usage_types import (
    NetRunUsage,
    RawTurnUsage,
    ResumptionBaseline,
)


class NetRunUsageMeter:
    """Calculates true delta token usage and cost for turns within resumed or continuous sessions."""

    # Default rates per 1,000,000 tokens (e.g. Claude 3.5 Sonnet standard pricing)
    DEFAULT_INPUT_RATE_PER_M = 3.00
    DEFAULT_OUTPUT_RATE_PER_M = 15.00
    DEFAULT_CACHE_DISCOUNT_RATIO = 0.10  # 90% discount on cached tokens (0.1x cost)

    def __init__(
        self,
        input_rate_per_m: float = DEFAULT_INPUT_RATE_PER_M,
        output_rate_per_m: float = DEFAULT_OUTPUT_RATE_PER_M,
        cache_discount_ratio: float = DEFAULT_CACHE_DISCOUNT_RATIO,
    ) -> None:
        self.input_rate_per_m = input_rate_per_m
        self.output_rate_per_m = output_rate_per_m
        self.cache_discount_ratio = cache_discount_ratio

    def calculate_net_run_usage(
        self,
        raw_usage: RawTurnUsage,
        baseline: ResumptionBaseline | None = None,
        is_first_resumed_turn: bool = False,
    ) -> NetRunUsage:
        """Derive net incremental token consumption by deducting legacy history from gross numbers."""
        gross_physical = raw_usage.gross_prompt_tokens + raw_usage.completion_tokens
        cache_hit_ratio = (
            raw_usage.cached_prompt_tokens / max(1, raw_usage.gross_prompt_tokens)
            if raw_usage.gross_prompt_tokens > 0
            else 0.0
        )

        if is_first_resumed_turn and baseline and baseline.resumed_history_tokens > 0:
            # Exclude pre-existing history from the new run's billable prompt
            excluded_history = min(raw_usage.gross_prompt_tokens, baseline.resumed_history_tokens)
            net_prompt = max(0, raw_usage.gross_prompt_tokens - excluded_history)
        else:
            excluded_history = 0
            net_prompt = raw_usage.gross_prompt_tokens

        net_billable = net_prompt + raw_usage.completion_tokens

        return NetRunUsage(
            net_prompt_tokens=net_prompt,
            completion_tokens=raw_usage.completion_tokens,
            net_billable_tokens=net_billable,
            excluded_history_tokens=excluded_history,
            cache_hit_ratio=round(cache_hit_ratio, 4),
            gross_physical_tokens=gross_physical,
        )

    def estimate_cost(self, net_usage: NetRunUsage, raw_usage: RawTurnUsage) -> float:
        """Compute dollar cost strictly on net incremental tokens, applying cache discounts where eligible."""
        # Uncached prompt tokens
        uncached_prompt = max(0, net_usage.net_prompt_tokens - raw_usage.cached_prompt_tokens)
        cached_prompt = min(net_usage.net_prompt_tokens, raw_usage.cached_prompt_tokens)

        cost_uncached = (uncached_prompt / 1_000_000.0) * self.input_rate_per_m
        cost_cached = (cached_prompt / 1_000_000.0) * self.input_rate_per_m * self.cache_discount_ratio
        cost_completion = (net_usage.completion_tokens / 1_000_000.0) * self.output_rate_per_m

        total_cost = cost_uncached + cost_cached + cost_completion
        return round(total_cost, 6)
