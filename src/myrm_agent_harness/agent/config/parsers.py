"""LiteLLM model name parsing and conversion utilities.

Provides generic string manipulation functions for working with LiteLLM model names.
No dependencies on business-layer configuration structures.

[INPUT]
- litellm_routing::litellm_route_prefix_for_effective (POS: LiteLLM 路由前缀单一事实源)

[OUTPUT]
- to_litellm_model: convert provider+model to LiteLLM format
- parse_litellm_model: parse LiteLLM model name to (provider, model)

[POS]
Framework-level utility for LiteLLM model name handling. Business layer can use
these functions to build LiteLLM-compatible model names from their own config structures.
"""

from __future__ import annotations

from myrm_agent_harness.agent.config.litellm_routing import litellm_route_prefix_for_effective


def to_litellm_model(provider: str, model: str, provider_type: str | None = None) -> str:
    """Convert provider + model to LiteLLM format.

    For built-in OpenAI provider (provider=="openai", no provider_type override),
    returns the bare model name (e.g. "gpt-4o").

    For custom providers with provider_type (e.g. a user-created "qwencoding" with
    provider_type="openai"), always adds the type prefix so LiteLLM knows which SDK
    to use (e.g. "openai/MiniMax-M2.5").

    Args:
        provider: Provider identifier (e.g. "openai", "anthropic")
        model: Model name (e.g. "gpt-4o", "claude-3-sonnet")
        provider_type: Optional provider type override (e.g. "openai" for OpenAI-compatible APIs)

    Returns:
        LiteLLM-formatted model name

    Examples:
        >>> to_litellm_model("openai", "gpt-4o")
        "gpt-4o"
        >>> to_litellm_model("anthropic", "claude-3-sonnet")
        "anthropic/claude-3-sonnet"
        >>> to_litellm_model("qwencoding", "qwen-max", "openai")
        "openai/qwen-max"
    """
    model_lower = model.lower()

    if model_lower.startswith("xiaomi_mimo/"):
        return model

    effective = provider_type or provider
    prefix = litellm_route_prefix_for_effective(effective)

    if prefix and model.startswith(prefix):
        return model

    return f"{prefix}{model}"


def parse_litellm_model(model_name: str) -> tuple[str, str]:
    """Parse a LiteLLM model name into (provider, model).

    Args:
        model_name: LiteLLM model name (e.g. "openai/gpt-4o", "gpt-4o")

    Returns:
        Tuple of (provider, model). Bare model names are assumed to be OpenAI.

    Examples:
        >>> parse_litellm_model("openai/gpt-4o")
        ("openai", "gpt-4o")
        >>> parse_litellm_model("anthropic/claude-3-sonnet")
        ("anthropic", "claude-3-sonnet")
        >>> parse_litellm_model("gpt-4o")
        ("openai", "gpt-4o")
    """
    if "/" in model_name:
        parts = model_name.split("/", 1)
        return parts[0], parts[1]
    return "openai", model_name


__all__ = [
    "parse_litellm_model",
    "to_litellm_model",
]
