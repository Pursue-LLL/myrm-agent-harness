"""[INPUT]
- (none)

[OUTPUT]
- calculate_cache_savings_usd: Calculate the estimated Net USD savings from cached token...

[POS]
Provides calculate_cache_savings_usd.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

logger = logging.getLogger(__name__)


def calculate_cache_savings_usd(
    usage: Mapping[str, object],
    model: str | None,
) -> float:
    """Calculate the estimated Net USD savings from cached tokens based on the model's pricing.
    This calculates Net Cache ROI by subtracting any cache write premiums.

    Args:
        usage: The token usage dictionary containing 'cached_tokens', 'prompt_tokens',
               and potentially 'cache_creation_input_tokens'.
        model: The name of the model used, to determine pricing.

    Returns:
        The estimated net savings in USD (can be negative if write premium exceeds read savings).
    """
    if not model or not usage:
        return 0.0

    try:
        import litellm
        from litellm import model_cost

        # Get cached read and write tokens
        cached_tokens = 0
        cache_creation_tokens = 0
        prompt_details = usage.get("prompt_tokens_details", {})

        if isinstance(prompt_details, dict):
            cached = prompt_details.get("cached_tokens")
            if isinstance(cached, (int, float)):
                cached_tokens = int(cached)

            creation = prompt_details.get("cache_creation_input_tokens")
            if isinstance(creation, (int, float)):
                cache_creation_tokens = int(creation)

        if not cached_tokens and not cache_creation_tokens:
            # Fallback for old format
            cached = usage.get("cached_tokens")
            if isinstance(cached, (int, float)):
                cached_tokens = int(cached)

        if cached_tokens <= 0 and cache_creation_tokens <= 0:
            return 0.0

        # Attempt to find the model in LiteLLM's cost dictionary
        pricing = model_cost.get(model)
        if not pricing:
            # Try to resolve aliased models (e.g. gpt-4o -> gpt-4o-2024-05-13)
            try:
                model_info = litellm.get_model_info(model)
                if model_info:
                    pricing = model_info
            except Exception:
                pass

        if not pricing:
            return 0.0

        input_cost_per_token = pricing.get("input_cost_per_token", 0.0)

        # Determine cache read cost and write cost per token
        cache_read_cost_per_token = pricing.get("cache_read_input_token_cost")

        # Some providers charge a premium for creating the cache (e.g., Anthropic charges 1.25x)
        # However, litellm model_cost might not always expose this clearly as a single variable.
        # We will try to get it, or use standard heuristics.
        # Anthropic standard: write is 1.25x base, read is 0.1x base.
        # So write premium = 0.25x base.

        cache_write_premium_per_token = 0.0

        if cache_read_cost_per_token is None:
            # DO NOT guess financial data. If the model provider or litellm registry does not declare
            # a specific cache discount, we strictly assume 0 savings to avoid false advertising.
            return 0.0
        else:
            # If litellm has the read cost, perfectly calculate write premium if defined.
            cache_creation_cost = pricing.get("cache_creation_input_token_cost")
            if cache_creation_cost is not None and cache_creation_cost > input_cost_per_token:
                cache_write_premium_per_token = cache_creation_cost - input_cost_per_token

        # Savings = (Cost without cache) - (Cost with cache)
        savings_per_read_token = input_cost_per_token - cache_read_cost_per_token

        gross_savings = cached_tokens * savings_per_read_token
        write_penalty = cache_creation_tokens * cache_write_premium_per_token

        net_savings = gross_savings - write_penalty

        return float(net_savings)

    except Exception as e:
        logger.debug("Failed to calculate cache savings for model %s: %s", model, e)
        return 0.0
