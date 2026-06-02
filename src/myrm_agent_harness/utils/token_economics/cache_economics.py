"""Prompt-cache input economics (hit rate and vs-uncached-input savings).

Defines hit-rate and savings formulas consumed by LLM response logging, optional NDJSON
metrics, and ``TokenUsage.get_cache_effectiveness()``.

[INPUT]

[OUTPUT]
- coerce_usage_non_negative_int(): normalize provider usage counters
- compute_prompt_cache_stats(): hit rate, savings pct, savings absolute

[POS]
Framework-neutral utilities under ``utils/``; safe for any layer to import.

## Pricing

``cache_read_ratio`` defaults to 0.1 (Anthropic: cache reads at 10% of base input).
Callers can override per-provider: OpenAI 0.5, DeepSeek 0.1, etc.
"""

import logging
import math

logger = logging.getLogger(__name__)

_UNCACHED_INPUT_COST_UNIT = 1.0


def coerce_usage_non_negative_int(value: object) -> int:
    """Coerce provider usage fields to non-negative int; invalid values become 0.

    LLM providers (LiteLLM) return usage as int or None. Other types indicate
    integration errors and should fail fast.
    """
    if value is None:
        return 0
    if isinstance(value, bool):
        msg = f"Expected int | float | None for usage field, got {type(value).__name__}"
        raise TypeError(msg)
    if isinstance(value, int):
        return max(value, 0)
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return 0
        return max(0, int(value))
    msg = f"Expected int | float | None for usage field, got {type(value).__name__}"
    raise TypeError(msg)


def compute_prompt_cache_stats(
    prompt_tokens: int,
    cached_tokens: int,
    *,
    cache_read_ratio: float = 0.1,
) -> dict[str, float]:
    """Compute cache hit rate and cost savings vs treating all prompt tokens as uncached input.

    Args:
        prompt_tokens: Provider ``prompt_tokens`` (non-negative).
        cached_tokens: Tokens billed as cache reads (non-negative).
        cache_read_ratio: Cache-read cost as fraction of base input cost.
            Anthropic: 0.1 (90% off), OpenAI: 0.5 (50% off), DeepSeek: 0.1.

    Returns:
        ``cache_hit_rate``, ``cost_savings_pct``, ``cost_savings_absolute``.

    Notes:
        - Hit rate clamped to [0, 1]. If ``cached_tokens > prompt_tokens``, logs warning
          and caps at 1.0 (indicates provider usage inconsistency).
    """
    if prompt_tokens <= 0:
        return {
            "cache_hit_rate": 0.0,
            "cost_savings_pct": 0.0,
            "cost_savings_absolute": 0.0,
        }

    hit_rate = cached_tokens / prompt_tokens
    if hit_rate > 1.0:
        logger.warning(
            "Cache hit rate exceeds 1.0 (cached_tokens=%d > prompt_tokens=%d), clamping to 1.0",
            cached_tokens,
            prompt_tokens,
        )
        hit_rate = 1.0

    original_cost = prompt_tokens * _UNCACHED_INPUT_COST_UNIT
    actual_cost = cached_tokens * cache_read_ratio + (prompt_tokens - cached_tokens) * _UNCACHED_INPUT_COST_UNIT
    savings_abs = original_cost - actual_cost
    savings_pct = savings_abs / original_cost if original_cost > 0 else 0.0

    return {
        "cache_hit_rate": hit_rate,
        "cost_savings_pct": savings_pct,
        "cost_savings_absolute": savings_abs,
    }
