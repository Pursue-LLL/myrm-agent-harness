# [INPUT]: CacheProviderType, ProviderCacheSpec from warmth_types
# [OUTPUT]: ProviderCacheMatrix, get_provider_cache_spec, calculate_cache_savings, calculate_probe_cost
# [POS]: myrm_agent_harness.agent.context_management.cache_warmth_keepalive.provider_cache_matrix
"""Multi-provider cache matrix for differential TTL and token cost economics (Item 328).

Translates provider endpoints, model identifiers, and flags into concrete
ProviderCacheSpec parameters.
"""

from __future__ import annotations

from typing import Final
from myrm_agent_harness.agent.context_management.cache_warmth_keepalive.warmth_types import (
    CacheProviderType,
    ProviderCacheSpec,
)

# Standard presets for well-known providers
_ANTHROPIC_EXTENDED_SPEC: Final[ProviderCacheSpec] = ProviderCacheSpec(
    provider_type=CacheProviderType.ANTHROPIC,
    default_ttl_seconds=300,
    extended_ttl_seconds=3600,
    critical_threshold_seconds=120,
    min_tokens_for_cache=1024,
    supports_explicit_keepalive=True,
    input_cost_per_m=3.0,
    cache_write_cost_per_m=3.75,
    cache_read_cost_per_m=0.30,
    cache_savings_ratio=0.90,
)

_ANTHROPIC_SHORT_SPEC: Final[ProviderCacheSpec] = ProviderCacheSpec(
    provider_type=CacheProviderType.ANTHROPIC,
    default_ttl_seconds=300,
    extended_ttl_seconds=300,
    critical_threshold_seconds=60,
    min_tokens_for_cache=1024,
    supports_explicit_keepalive=True,
    input_cost_per_m=3.0,
    cache_write_cost_per_m=3.75,
    cache_read_cost_per_m=0.30,
    cache_savings_ratio=0.90,
)

_OPENAI_SPEC: Final[ProviderCacheSpec] = ProviderCacheSpec(
    provider_type=CacheProviderType.OPENAI,
    default_ttl_seconds=300,
    extended_ttl_seconds=600,
    critical_threshold_seconds=60,
    min_tokens_for_cache=1024,
    supports_explicit_keepalive=False,  # Automatic server-side prefix cache without explicit TTL renewal
    input_cost_per_m=2.50,
    cache_write_cost_per_m=2.50,
    cache_read_cost_per_m=1.25,
    cache_savings_ratio=0.50,
)

_DEEPSEEK_SPEC: Final[ProviderCacheSpec] = ProviderCacheSpec(
    provider_type=CacheProviderType.DEEPSEEK,
    default_ttl_seconds=1800,
    extended_ttl_seconds=3600,
    critical_threshold_seconds=180,
    min_tokens_for_cache=64,
    supports_explicit_keepalive=True,
    input_cost_per_m=0.14,
    cache_write_cost_per_m=0.14,
    cache_read_cost_per_m=0.014,
    cache_savings_ratio=0.90,
)

_GEMINI_SPEC: Final[ProviderCacheSpec] = ProviderCacheSpec(
    provider_type=CacheProviderType.GEMINI,
    default_ttl_seconds=3600,
    extended_ttl_seconds=3600,
    critical_threshold_seconds=300,
    min_tokens_for_cache=32768,
    supports_explicit_keepalive=True,
    input_cost_per_m=1.25,
    cache_write_cost_per_m=1.25,
    cache_read_cost_per_m=0.30,
    cache_savings_ratio=0.76,
)

_GENERIC_SPEC: Final[ProviderCacheSpec] = ProviderCacheSpec(
    provider_type=CacheProviderType.GENERIC,
    default_ttl_seconds=300,
    extended_ttl_seconds=300,
    critical_threshold_seconds=60,
    min_tokens_for_cache=1024,
    supports_explicit_keepalive=False,
    input_cost_per_m=2.00,
    cache_write_cost_per_m=2.00,
    cache_read_cost_per_m=1.00,
    cache_savings_ratio=0.50,
)


class ProviderCacheMatrix:
    """Matrix resolver for provider cache parameters."""

    @classmethod
    def resolve_spec(
        cls,
        model_name: str,
        base_url: str = "",
        is_long_ttl: bool = True,
    ) -> ProviderCacheSpec:
        """Resolve differential cache specification according to model and endpoint."""
        lower_model = (model_name or "").lower()
        lower_url = (base_url or "").lower()

        # 1. Anthropic direct or Vertex
        if "anthropic" in lower_model or "claude" in lower_model:
            is_direct_eligible = (
                "api.anthropic.com" in lower_url
                or "aiplatform.googleapis.com" in lower_url
                or not base_url  # LiteLLM direct routing
            )
            if is_direct_eligible and is_long_ttl:
                return _ANTHROPIC_EXTENDED_SPEC
            return _ANTHROPIC_SHORT_SPEC

        # 2. DeepSeek
        if "deepseek" in lower_model:
            return _DEEPSEEK_SPEC

        # 3. Gemini / Google Vertex
        if "gemini" in lower_model or "google" in lower_model:
            return _GEMINI_SPEC

        # 4. OpenAI
        if "gpt" in lower_model or "o1" in lower_model or "o3" in lower_model or "openai" in lower_model:
            return _OPENAI_SPEC

        # 5. Default generic fallback
        return _GENERIC_SPEC


def get_provider_cache_spec(
    model_name: str,
    base_url: str = "",
    is_long_ttl: bool = True,
) -> ProviderCacheSpec:
    """Convenience functional resolver for provider cache spec."""
    return ProviderCacheMatrix.resolve_spec(
        model_name=model_name,
        base_url=base_url,
        is_long_ttl=is_long_ttl,
    )


def calculate_cache_savings(
    cached_tokens: int,
    spec: ProviderCacheSpec,
    hit_count: int = 1,
) -> tuple[int, float]:
    """Calculate cumulative tokens saved and USD cost saved upon cache hit.

    Args:
        cached_tokens: Number of prompt tokens hitting cache.
        spec: Provider pricing and savings spec.
        hit_count: Number of turns cache was read.

    Returns:
        tuple of (total_tokens_saved, total_usd_saved)
    """
    if cached_tokens <= 0 or hit_count <= 0:
        return (0, 0.0)

    total_tokens = cached_tokens * hit_count
    # Standard cost vs cached read cost
    full_price = (total_tokens / 1_000_000.0) * spec.input_cost_per_m
    cache_price = (total_tokens / 1_000_000.0) * spec.cache_read_cost_per_m
    cost_saved = max(0.0, full_price - cache_price)

    return (total_tokens, round(cost_saved, 6))


def calculate_probe_cost(
    cached_tokens: int,
    spec: ProviderCacheSpec,
    probe_tokens: int = 1,
) -> float:
    """Calculate the microscopic USD cost of dispatching a 1-token keep-alive probe."""
    if cached_tokens <= 0:
        return 0.0

    # Probe reads existing cache prefix at cache_read rate + 1 output token
    read_cost = (cached_tokens / 1_000_000.0) * spec.cache_read_cost_per_m
    # 1 token output cost approximated at 4x input cost
    out_cost = (probe_tokens / 1_000_000.0) * (spec.input_cost_per_m * 4.0)
    return round(read_cost + out_cost, 6)
