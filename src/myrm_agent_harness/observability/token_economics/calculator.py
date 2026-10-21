"""
[INPUT]: TokenUsageSnapshot with prompt, cached tokens, and completion tokens.
[OUTPUT]: CacheSavingsMetrics computing baseline cost, actual cost, net saved RMB, and savings percentage.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/token_economics/calculator.py
"""

from typing import Dict, Optional

from .models import CacheSavingsMetrics, ModelPricingRate, TokenUsageSnapshot


class CacheRoiCalculator:
    """
    Computes transparent Token economics and prompt-cache ROI against standard model price matrices.
    """

    _DEFAULT_PRICING: Dict[str, ModelPricingRate] = {
        "deepseek-chat": ModelPricingRate(
            model_name="deepseek-chat",
            prompt_cpm=1.0,
            completion_cpm=2.0,
            cache_hit_cpm=0.1,  # 90% cache discount
        ),
        "deepseek-reasoner": ModelPricingRate(
            model_name="deepseek-reasoner",
            prompt_cpm=4.0,
            completion_cpm=16.0,
            cache_hit_cpm=1.0,
        ),
        "claude-3-5-sonnet": ModelPricingRate(
            model_name="claude-3-5-sonnet",
            prompt_cpm=21.0,
            completion_cpm=105.0,
            cache_hit_cpm=2.1,  # 90% cache discount
        ),
        "gpt-4o": ModelPricingRate(
            model_name="gpt-4o",
            prompt_cpm=17.5,
            completion_cpm=70.0,
            cache_hit_cpm=8.75,  # 50% cache discount
        ),
        "qwen-max": ModelPricingRate(
            model_name="qwen-max",
            prompt_cpm=20.0,
            completion_cpm=60.0,
            cache_hit_cpm=4.0,
        ),
    }

    _FALLBACK_RATE = ModelPricingRate(
        model_name="fallback-generic",
        prompt_cpm=10.0,
        completion_cpm=30.0,
        cache_hit_cpm=1.5,
    )

    def __init__(self, custom_rates: Optional[Dict[str, ModelPricingRate]] = None) -> None:
        self._rates = dict(self._DEFAULT_PRICING)
        if custom_rates:
            self._rates.update(custom_rates)

    def get_rate(self, model_name: str) -> ModelPricingRate:
        normalized = model_name.strip().lower()
        for k, v in self._rates.items():
            if k in normalized:
                return v
        return self._FALLBACK_RATE

    def calculate_savings(
        self,
        snapshot: TokenUsageSnapshot,
        override_rate: Optional[ModelPricingRate] = None,
    ) -> CacheSavingsMetrics:
        rate = override_rate or self.get_rate(snapshot.model_name)
        total_prompt = max(0, snapshot.total_prompt_tokens)
        cached_prompt = min(total_prompt, max(0, snapshot.cached_prompt_tokens))
        uncached_prompt = total_prompt - cached_prompt
        completion = max(0, snapshot.completion_tokens)

        cache_hit_rate_pct = (
            round((cached_prompt / total_prompt) * 100.0, 2) if total_prompt > 0 else 0.0
        )

        # Baseline cost: assume 0 cache hit, all input tokens billed at standard prompt_cpm
        baseline_cost = (total_prompt / 1_000_000.0) * rate.prompt_cpm + (
            completion / 1_000_000.0
        ) * rate.completion_cpm

        # Actual cost: uncached at prompt_cpm, cached at cache_hit_cpm
        actual_cost = (
            (uncached_prompt / 1_000_000.0) * rate.prompt_cpm
            + (cached_prompt / 1_000_000.0) * rate.cache_hit_cpm
            + (completion / 1_000_000.0) * rate.completion_cpm
        )

        saved_amount = max(0.0, baseline_cost - actual_cost)
        saved_pct = (
            round((saved_amount / baseline_cost) * 100.0, 2) if baseline_cost > 0.0 else 0.0
        )

        return CacheSavingsMetrics(
            task_id=snapshot.task_id,
            model_name=rate.model_name,
            cache_hit_rate_pct=cache_hit_rate_pct,
            baseline_cost_rmb=round(baseline_cost, 4),
            actual_cost_rmb=round(actual_cost, 4),
            saved_amount_rmb=round(saved_amount, 4),
            saved_percentage=saved_pct,
        )
